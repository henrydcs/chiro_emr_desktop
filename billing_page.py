# billing_page.py — Billing workspace: shadow preview + Phase 2 cash checkout.
from __future__ import annotations

import tkinter as tk
import os
from pathlib import Path
from tkinter import messagebox, ttk

from billing_engine import classify_exam_type, determine_payer_mode
from billing_case_export import save_case_exports
from closeout_dialog import CloseoutDialog
from billing_ledger import (
    compute_cash_balance,
    encounter_amount_due,
    is_encounter_posted,
    load_posted_encounter,
    post_encounter_to_cash_ledger,
    record_payment,
)
from billing_pi_case import case_status_label, load_or_create_pi_case
from billing_pi_ledger import (
    compute_pi_balance,
    is_encounter_pi_posted,
    is_pi_case_settled,
    load_pi_posted_encounter,
    pi_encounter_amount_due,
    post_encounter_to_pi_case,
    preview_pi_settlement,
    record_pi_adjustment,
    record_pi_payment,
    record_pi_settlement,
)
from billing_case_export import build_case_summary_text, save_case_exports
from billing_receipt import (
    BillingDocument,
    STREAM_DISPLAY_LABELS,
    archive_pi_summary_to_receipts,
    build_receipt_text,
    build_settlement_receipt_text,
    ensure_receipt_subfolders,
    list_billing_documents,
    open_receipts_folder,
    receipt_display_label,
    save_receipt_file,
)
from billing_pdf import (
    REPORTLAB_OK as _BILLING_PDF_OK,
    build_cash_receipt_to_receipts,
    build_pi_case_to_receipts,
)
from billing_storage import load_or_refresh_shadow_encounter
from package_pdf import build_contract_pdf
from fee_schedule_dialog import FeeScheduleDialog
from package_dialogs import (
    CancelPackageDialog,
    CatalogEditorDialog,
    PackageDetailDialog,
    PackagePostVisitDialog,
    PackageTakePaymentDialog,
    RefundPackageDialog,
    SellPackageDialog,
)
from package_engine import (
    aggregate_revenue,
    compute_package_state,
    is_redeemable,
    states_for_patient,
    status_label,
)
from package_storage import (
    EVENT_REDEMPTION,
    all_events_for_package,
    is_encounter_package_posted,
    list_packages,
    load_package_log,
    load_package_posted_encounter,
    reconcile_pending_operations,
)
from pi_case_dialog import PiCaseEditorDialog

# Reuse shell palette (import after shell defines constants — no circular class deps)
from shell_app import (
    COLOR_ACCENT,
    COLOR_BG_APP,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_GREEN,
    COLOR_MUTED,
    COLOR_RED,
    COLOR_TEXT,
    FONT_BASE,
    FONT_BASE_BOLD,
    FONT_SECTION,
    FONT_SMALL,
    FONT_TITLE,
    collect_visits_for_patient,
    make_card,
    read_shell_state,
    write_shell_state,
)

# Encounter list (left column) — default, hover, and active selection
COLOR_VISIT_ROW = COLOR_CARD
COLOR_VISIT_ROW_HOVER = "#F8FAFC"
COLOR_VISIT_ROW_SELECTED = "#F5EDE0"
COLOR_VISIT_ROW_SELECTED_BORDER = "#D9CCB0"

# Per-flow visit-row tints. A row's bg is chosen by which flow posted the visit:
#   cash    → pastel yellow + "CASH" badge
#   package → pastel purple + "Pckg$" badge
#   pi      → pastel blue   + "PI" badge
# If multiple posts exist (legacy / dual-posted visits), priority is package > pi
# > cash for the background tint, but EVERY applicable badge is shown.
COLOR_VISIT_ROW_CASH = "#FEF9C3"
COLOR_VISIT_ROW_CASH_HOVER = "#FEF08A"
COLOR_VISIT_ROW_CASH_BORDER = "#EAB308"
COLOR_VISIT_ROW_CASH_BORDER_SELECTED = "#A16207"     # yellow-700 — bolder

COLOR_VISIT_ROW_PACKAGE = "#F3E8FF"
COLOR_VISIT_ROW_PACKAGE_HOVER = "#E9D5FF"
COLOR_VISIT_ROW_PACKAGE_BORDER = "#A855F7"
COLOR_VISIT_ROW_PACKAGE_BORDER_SELECTED = "#7E22CE"  # purple-700 — bolder

COLOR_VISIT_ROW_PI = "#DBEAFE"
COLOR_VISIT_ROW_PI_HOVER = "#BFDBFE"
COLOR_VISIT_ROW_PI_BORDER = "#3B82F6"
COLOR_VISIT_ROW_PI_BORDER_SELECTED = "#1D4ED8"       # blue-700 — bolder

# Unposted-row selected border — bolder neutral grey for visibility on white.
COLOR_VISIT_ROW_BORDER_SELECTED = "#475569"          # slate-600

# Border width: thin default, thick when the card is the active selection.
VISIT_ROW_BORDER_THICKNESS = 1
VISIT_ROW_BORDER_THICKNESS_SELECTED = 3

_VISIT_ROW_SYNC_BGS = frozenset({
    COLOR_VISIT_ROW,
    COLOR_VISIT_ROW_HOVER,
    COLOR_VISIT_ROW_SELECTED,
    "#F8FAFC",
    COLOR_VISIT_ROW_CASH,
    COLOR_VISIT_ROW_CASH_HOVER,
    COLOR_VISIT_ROW_PACKAGE,
    COLOR_VISIT_ROW_PACKAGE_HOVER,
    COLOR_VISIT_ROW_PI,
    COLOR_VISIT_ROW_PI_HOVER,
})


class BillingPage(tk.Frame):
    """Cash checkout: preview charges, post, take payment, receipt."""

    def __init__(self, parent: tk.Misc, shell: "ShellLayout"):
        super().__init__(parent, bg=COLOR_BG_APP)
        self.shell = shell
        self.current_user = getattr(shell, "current_user", "") or ""
        self.active_patient: dict | None = None
        self._visits: list[dict] = []
        self._selected_visit: dict | None = None
        self._current_encounter: dict | None = None
        self._posted_encounter: dict | None = None
        self._posted_pi_encounter: dict | None = None
        self._posted_package_encounter: dict | None = None
        self._billing_panel = "cash"
        self._last_payment: dict | None = None
        self._visit_row_by_path: dict[str, tk.Frame] = {}
        # Warnings for the currently-selected encounter, surfaced on demand
        # by a "Review warnings" button in each flow's action row (the old
        # inline Review warnings card has been retired).
        self._current_warnings: list[dict] = []
        self._warnings_buttons: list[tk.Button] = []

        self._build()
        self.bind("<Map>", lambda _e: self._on_map())

    def _on_map(self) -> None:
        self._sync_patient_from_shell()

    def set_active_patient(self, patient: dict | None) -> None:
        self.active_patient = patient
        self._refresh_patient_header()
        self._load_visits()

    def _sync_patient_from_shell(self) -> None:
        keep_path = (self._selected_visit or {}).get("path") or ""
        state = read_shell_state()
        pid = (state.get("active_patient_id") or state.get("patient_id") or "").strip()
        folder = (state.get("active_patient_folder") or state.get("patient_folder") or "").strip()
        if not pid and not folder:
            doc = getattr(self.shell, "documents_page", None)
            if doc and doc.active_patient:
                self.set_active_patient(doc.active_patient)
                self._reselect_visit_by_path(keep_path)
            return
        if folder:
            folder_path = Path(folder)
            from shell_app import patient_record_from_folder

            rec = patient_record_from_folder(folder_path)
            if rec:
                self.set_active_patient(rec)
                self._reselect_visit_by_path(keep_path)
                return
        if pid and self.active_patient and self.active_patient.get("patient_id") == pid:
            self._load_visits()
            self._reselect_visit_by_path(keep_path)
            return
        doc = getattr(self.shell, "documents_page", None)
        if doc and doc.active_patient:
            self.set_active_patient(doc.active_patient)
            self._reselect_visit_by_path(keep_path)

    def _reselect_visit_by_path(self, exam_path: str) -> None:
        """Re-select a visit after reload so billing preview picks up chart changes."""
        if not exam_path:
            return
        for visit in self._visits:
            if visit.get("path") == exam_path:
                self._select_visit(visit)
                return

    def _persist_shell_patient(self) -> None:
        if not self.active_patient:
            return
        write_shell_state({
            "active_patient_id": self.active_patient.get("patient_id"),
            "active_patient_folder": self.active_patient.get("folder"),
            "active_patient_label": self.active_patient.get("label"),
        })

    def _patient_display_name(self) -> str:
        if not self.active_patient:
            return "—"
        raw = (
            self.active_patient.get("label")
            or self.active_patient.get("display")
            or self.active_patient.get("name")
            or "—"
        )
        return raw.split("    DOB")[0].strip() if "    DOB" in raw else raw.strip()

    def _make_billing_panel_shell(self, parent: tk.Frame) -> tk.Frame:
        """Opaque full-area frame so tkraise panels fully cover each other."""
        return tk.Frame(parent, bg=COLOR_BG_APP)

    def _show_billing_panel(self, panel: str) -> None:
        panel = (panel or "cash").strip().lower()
        if panel not in ("cash", "pi", "insurance", "packages", "memberships"):
            panel = "cash"
        self._billing_panel = panel
        for key, shell in self._panel_frames.items():
            if key == panel:
                shell.tkraise()
                shell.lift()
            btn = self._panel_nav_btns.get(key)
            if btn:
                if key == panel:
                    btn.configure(
                        bg=COLOR_ACCENT,
                        fg="#FFFFFF",
                        font=FONT_BASE_BOLD,
                    )
                else:
                    btn.configure(
                        bg=COLOR_CARD,
                        fg=COLOR_TEXT,
                        font=FONT_BASE,
                    )
        self._refresh_receipt_preview()

    def _build(self) -> None:
        outer = tk.Frame(self, bg=COLOR_BG_APP)
        outer.pack(fill="both", expand=True, padx=16, pady=16)

        header = tk.Frame(outer, bg=COLOR_BG_APP)
        header.pack(fill="x", pady=(0, 6))

        self.billing_for_var = tk.StringVar(value="Billing for: —")
        tk.Label(
            header,
            textvariable=self.billing_for_var,
            bg=COLOR_BG_APP,
            fg=COLOR_TEXT,
            font=FONT_TITLE,
        ).pack(side="left")

        actions = tk.Frame(header, bg=COLOR_BG_APP)
        actions.pack(side="right")
        tk.Button(
            actions,
            text="Fee schedule",
            command=self._open_fee_schedule,
            bg=COLOR_BG_APP,
            fg=COLOR_ACCENT,
            relief="flat",
            bd=0,
            font=FONT_BASE,
            cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            actions,
            text="Open Documents",
            command=lambda: self.shell.show_page("documents"),
            bg=COLOR_BG_APP,
            fg=COLOR_ACCENT,
            relief="flat",
            bd=0,
            font=FONT_BASE,
            cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            actions,
            text="Refresh from chart",
            command=self._rebuild_selected,
            bg=COLOR_ACCENT,
            fg="#FFFFFF",
            relief="flat",
            bd=0,
            font=FONT_BASE_BOLD,
            padx=12,
            pady=4,
            cursor="hand2",
        ).pack(side="left")

        balance_row = tk.Frame(outer, bg=COLOR_BG_APP)
        balance_row.pack(fill="x", pady=(0, 8))
        self.balance_var = tk.StringVar(value="")
        tk.Label(
            balance_row,
            textvariable=self.balance_var,
            bg=COLOR_BG_APP,
            fg=COLOR_TEXT,
            font=FONT_BASE_BOLD,
        ).pack(anchor="w")

        nav_row = tk.Frame(outer, bg=COLOR_BG_APP)
        nav_row.pack(fill="x", pady=(0, 10))
        self._panel_nav_btns: dict[str, tk.Button] = {}
        self._panel_frames: dict[str, tk.Frame] = {}
        for key, label in [
            ("cash", "Cash checkout"),
            ("pi", "PI ledger"),
            ("insurance", "Insurance"),
            ("packages", "Package deals"),
            ("memberships", "Memberships"),
        ]:
            btn = tk.Button(
                nav_row,
                text=label,
                command=lambda k=key: self._show_billing_panel(k),
                bg=COLOR_CARD,
                fg=COLOR_TEXT,
                relief="flat",
                font=FONT_BASE,
                padx=12,
                pady=6,
                cursor="hand2",
            )
            btn.pack(side="left", padx=(0, 6))
            self._panel_nav_btns[key] = btn

        # Single Review-warnings button anchored to the far-right end of the
        # tab row — visible regardless of which flow is active. Color + label
        # auto-update with the current encounter's warning count.
        self._make_review_warnings_button(nav_row, side="right", padx=(6, 0), pady=6)

        body = tk.Frame(outer, bg=COLOR_BG_APP)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0, minsize=210)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left_card = tk.Frame(
            body,
            bg=COLOR_CARD,
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_BORDER,
            highlightthickness=1,
            bd=0,
        )
        left_card.configure(width=210)
        left_card.pack_propagate(False)
        left_card.grid_propagate(False)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        enc_header = tk.Frame(left_card, bg=COLOR_CARD)
        enc_header.pack(pady=(12, 6))
        tk.Label(
            enc_header,
            text="Encounters",
            bg=COLOR_CARD,
            fg=COLOR_TEXT,
            font=FONT_SECTION,
        ).pack(side="left")
        tk.Label(
            enc_header,
            text="  · Select a visit",
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            font=FONT_SMALL,
        ).pack(side="left")

        left_body = tk.Frame(left_card, bg=COLOR_CARD)
        left_body.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        enc_scroll = ttk.Scrollbar(left_body, orient="vertical")
        self.enc_canvas = tk.Canvas(
            left_body,
            bg=COLOR_CARD,
            highlightthickness=0,
            yscrollcommand=enc_scroll.set,
        )
        enc_scroll.config(command=self.enc_canvas.yview)
        self.enc_inner = tk.Frame(self.enc_canvas, bg=COLOR_CARD)
        self._enc_window = self.enc_canvas.create_window(
            (0, 0), window=self.enc_inner, anchor="nw"
        )
        enc_scroll.pack(side="right", fill="y")
        self.enc_canvas.pack(side="left", fill="both", expand=True)
        self.enc_inner.bind(
            "<Configure>",
            lambda _e: self.enc_canvas.configure(scrollregion=self.enc_canvas.bbox("all")),
        )
        self.enc_canvas.bind(
            "<Configure>",
            lambda e: self.enc_canvas.itemconfigure(self._enc_window, width=e.width),
        )

        right = tk.Frame(body, bg=COLOR_BG_APP)
        right.grid(row=0, column=1, sticky="nsew")
        # 3-column grid: col 0 + col 1 together hold Visit total + the active
        # billing panel (Cash / PI / Package deals / Insurance / Memberships)
        # via columnspan=2; col 2 hosts the Document preview. Weights 2/2/1
        # give the left side ~80% of any extra horizontal space, so package /
        # PI tables aren't squeezed by the (text-only) preview column.
        # Row 2 is the expanding row that now holds the full-width Charge
        # lines panel.
        right.columnconfigure(0, weight=2)
        right.columnconfigure(1, weight=2)
        right.columnconfigure(2, weight=1)
        right.rowconfigure(2, weight=1)

        totals_card, totals_body = make_card(right, "Visit total")
        totals_card.grid(
            row=0, column=0, columnspan=2,
            sticky="nsew", padx=(0, 6), pady=(0, 10),
        )
        self.totals_frame = tk.Frame(totals_body, bg=COLOR_CARD)
        self.totals_frame.pack(fill="x")

        receipt_card, receipt_body = make_card(
            right,
            "Document preview",
            "Cash receipt · PI settlement · case summary",
        )
        # rowspan=2 (was 3) so the preview ends at the bottom of the panel
        # host (row 1), aligning with the View detail / Refund row of the
        # Package deals panel. The vertical space below (row 2) is reclaimed
        # by Charge lines.
        receipt_card.grid(
            row=0, column=2, rowspan=2,
            sticky="nsew", padx=(6, 0), pady=(0, 10),
        )
        receipt_body.rowconfigure(1, weight=1)
        receipt_body.columnconfigure(0, weight=1)

        pdf_bar = tk.Frame(receipt_body, bg=COLOR_CARD)
        pdf_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.btn_create_pdf = tk.Button(
            pdf_bar,
            text="Create PDF",
            command=self._create_pdf_from_preview,
            bg=COLOR_ACCENT,
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=12,
            pady=4,
            cursor="hand2",
            state="disabled",
        )
        self.btn_create_pdf.pack(side="right")
        self.pdf_hint_var = tk.StringVar(value="")
        tk.Label(
            pdf_bar,
            textvariable=self.pdf_hint_var,
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            font=FONT_SMALL,
        ).pack(side="right", padx=(0, 10))
        self.receipt_preview = tk.Text(
            receipt_body,
            height=10,
            width=46,  # narrower natural width so col 2 can shrink and let
                       # the Package deals / Visit total side breathe
            wrap="word",
            font=("Consolas", 10),
            bg="#FAFAFA",
            fg=COLOR_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            state="disabled",
        )
        rvsb = ttk.Scrollbar(receipt_body, orient="vertical", command=self.receipt_preview.yview)
        self.receipt_preview.configure(yscrollcommand=rvsb.set)
        self.receipt_preview.grid(row=1, column=0, sticky="nsew")
        rvsb.grid(row=1, column=1, sticky="ns")
        self._set_receipt_preview_text("Select a visit to preview a receipt.")

        panel_host = tk.Frame(right, bg=COLOR_BG_APP)
        panel_host.grid(
            row=1, column=0, columnspan=2,
            sticky="new", padx=(0, 6), pady=(0, 10),
        )
        panel_host.columnconfigure(0, weight=1)

        cash_frame = self._make_billing_panel_shell(panel_host)
        checkout_card, checkout_body = make_card(cash_frame, "Cash checkout", "Desk payment · receipt")
        checkout_card.pack(fill="x", anchor="n")
        ck = tk.Frame(checkout_body, bg=COLOR_CARD)
        ck.pack(fill="x")
        self.btn_post = tk.Button(
            ck,
            text="Post cash",
            command=self._post_charges,
            bg=COLOR_ACCENT,
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=14,
            pady=6,
            cursor="hand2",
        )
        self.btn_post.pack(side="left", padx=(0, 8))
        self.btn_pay = tk.Button(
            ck,
            text="Take payment",
            command=self._take_payment,
            bg=COLOR_GREEN,
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=14,
            pady=6,
            cursor="hand2",
            state="disabled",
        )
        self.btn_pay.pack(side="left", padx=(0, 8))
        self.btn_receipt = tk.Button(
            ck,
            text="Receipt",
            command=self._show_receipt,
            bg=COLOR_CARD,
            fg=COLOR_ACCENT,
            relief="flat",
            font=FONT_BASE_BOLD,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            padx=14,
            pady=6,
            cursor="hand2",
            state="disabled",
        )
        self.btn_receipt.pack(side="left", padx=(0, 8))
        self.btn_receipt_folder = tk.Button(
            ck,
            text="Receipt folder",
            command=lambda: self._show_receipt_folder(stream="cash"),
            bg=COLOR_CARD,
            fg=COLOR_ACCENT,
            relief="flat",
            font=FONT_BASE_BOLD,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            padx=14,
            pady=6,
            cursor="hand2",
            state="disabled",
        )
        self.btn_receipt_folder.pack(side="left", padx=(0, 8))
        self.btn_sell_package = tk.Button(
            ck,
            text="Sell package",
            command=self._sell_package_from_cash,
            bg="#0D9488",
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=14,
            pady=6,
            cursor="hand2",
            state="disabled",
        )
        self.btn_sell_package.pack(side="left")
        self.checkout_status_var = tk.StringVar(value="Select a visit to begin checkout.")
        tk.Label(
            checkout_body,
            textvariable=self.checkout_status_var,
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            font=FONT_SMALL,
        ).pack(anchor="w", pady=(8, 0))
        tk.Frame(cash_frame, bg=COLOR_BG_APP).pack(fill="both", expand=True)

        pi_frame = self._make_billing_panel_shell(panel_host)
        pi_card, pi_body = make_card(pi_frame, "PI case ledger", "Post visits · payments · close-out packet")
        pi_card.pack(fill="x", anchor="n")
        pi_ck = tk.Frame(pi_body, bg=COLOR_CARD)
        pi_ck.pack(fill="x")
        self.pi_balance_var = tk.StringVar(value="")
        self.pi_case_var = tk.StringVar(value="")
        self.btn_post_pi = tk.Button(
            pi_ck,
            text="Post to PI case",
            command=self._post_pi_charges,
            bg="#7C3AED",
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=12,
            pady=6,
            cursor="hand2",
            state="disabled",
        )
        self.btn_post_pi.pack(side="left", padx=(0, 6))
        self.btn_pi_pay = tk.Button(
            pi_ck,
            text="PI payment",
            command=self._take_pi_payment,
            bg="#6D28D9",
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=12,
            pady=6,
            cursor="hand2",
            state="disabled",
        )
        self.btn_pi_pay.pack(side="left", padx=(0, 6))
        self.btn_record_settlement = tk.Button(
            pi_ck,
            text="Record settlement",
            command=self._record_settlement,
            bg="#047857",
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=12,
            pady=6,
            cursor="hand2",
            state="disabled",
        )
        self.btn_record_settlement.pack(side="left", padx=(0, 6))
        self.btn_export_case = tk.Button(
            pi_ck,
            text="Export case",
            command=self._export_pi_case,
            bg=COLOR_CARD,
            fg="#7C3AED",
            relief="flat",
            font=FONT_BASE_BOLD,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            padx=10,
            pady=6,
            cursor="hand2",
            state="disabled",
        )
        self.btn_export_case.pack(side="left", padx=(0, 6))
        self.btn_closeout = tk.Button(
            pi_ck,
            text="Attorney packet",
            command=self._open_closeout,
            bg="#5B21B6",
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=10,
            pady=6,
            cursor="hand2",
            state="disabled",
        )
        self.btn_closeout.pack(side="left", padx=(0, 6))
        self.btn_edit_case = tk.Button(
            pi_ck,
            text="Edit case",
            command=self._edit_pi_case,
            bg=COLOR_CARD,
            fg=COLOR_ACCENT,
            relief="flat",
            font=FONT_BASE,
            padx=8,
            pady=6,
            cursor="hand2",
            state="disabled",
        )
        self.btn_edit_case.pack(side="left", padx=(0, 6))
        self.btn_pi_adjust = tk.Button(
            pi_ck,
            text="Adjustment",
            command=self._pi_adjustment,
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            relief="flat",
            font=FONT_BASE,
            padx=8,
            pady=6,
            cursor="hand2",
            state="disabled",
        )
        self.btn_pi_adjust.pack(side="left", padx=(0, 8))
        self.btn_pi_receipt_folder = tk.Button(
            pi_ck,
            text="Receipt folder",
            command=lambda: self._show_receipt_folder(stream="pi"),
            bg=COLOR_CARD,
            fg=COLOR_ACCENT,
            relief="flat",
            font=FONT_BASE_BOLD,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            padx=14,
            pady=6,
            cursor="hand2",
            state="disabled",
        )
        self.btn_pi_receipt_folder.pack(side="left")
        self.pi_checkout_status_var = tk.StringVar(
            value="PI ledger available when patient is typed PI/Auto."
        )
        tk.Label(
            pi_body,
            textvariable=self.pi_balance_var,
            bg=COLOR_CARD,
            fg="#7C3AED",
            font=FONT_BASE_BOLD,
        ).pack(anchor="w", pady=(8, 0))
        tk.Label(
            pi_body,
            textvariable=self.pi_case_var,
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            font=FONT_SMALL,
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(
            pi_body,
            textvariable=self.pi_checkout_status_var,
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            font=FONT_SMALL,
        ).pack(anchor="w", pady=(6, 0))
        tk.Frame(pi_frame, bg=COLOR_BG_APP).pack(fill="both", expand=True)

        insurance_frame = self._make_billing_panel_shell(panel_host)
        self._build_wip_panel(insurance_frame, "Insurance billing", stream="insurance")
        tk.Frame(insurance_frame, bg=COLOR_BG_APP).pack(fill="both", expand=True)

        packages_frame = self._make_billing_panel_shell(panel_host)
        self._build_packages_panel(packages_frame)
        tk.Frame(packages_frame, bg=COLOR_BG_APP).pack(fill="both", expand=True)

        memberships_frame = self._make_billing_panel_shell(panel_host)
        self._build_wip_panel(memberships_frame, "Memberships", stream="membership")
        tk.Frame(memberships_frame, bg=COLOR_BG_APP).pack(fill="both", expand=True)

        shell_frames = {
            "cash": cash_frame,
            "pi": pi_frame,
            "insurance": insurance_frame,
            "packages": packages_frame,
            "memberships": memberships_frame,
        }
        for key, shell in shell_frames.items():
            shell.grid(row=0, column=0, sticky="nsew")
            self._panel_frames[key] = shell

        panel_host.update_idletasks()
        panel_h = max(shell.winfo_reqheight() for shell in shell_frames.values())
        panel_host.configure(height=max(panel_h, 200))
        panel_host.grid_propagate(False)
        self._show_billing_panel("cash")

        # Charge lines spans the full width of the right pane (cols 0-2) and
        # claims all the vertical space row 2 makes available — both the slot
        # the old Review warnings card used to occupy AND the space the now-
        # shorter Document preview gave up. Review warnings is now a popup,
        # opened by a per-flow "Review warnings" button below.
        lines_card, lines_body = make_card(right, "Charge lines", "Derived from Services Provided Today")
        lines_card.grid(row=2, column=0, columnspan=3, sticky="nsew")
        lines_body.rowconfigure(0, weight=1)
        lines_body.columnconfigure(0, weight=1)

        cols = ("cpt", "mod", "desc", "units", "dx", "cash", "pi")
        self.lines_tree = ttk.Treeview(
            lines_body,
            columns=cols,
            show="headings",
            height=12,
            selectmode="browse",
        )
        for col, title, w in [
            ("cpt", "CPT", 70),
            ("mod", "Mod", 44),
            ("desc", "Description", 200),
            ("units", "Units", 50),
            ("dx", "DX ptr", 90),
            ("cash", "Cash $", 72),
            ("pi", "PI/UCR $", 72),
        ]:
            self.lines_tree.heading(col, text=title)
            self.lines_tree.column(col, width=w, anchor="w" if col == "desc" else "center")
        vsb = ttk.Scrollbar(lines_body, orient="vertical", command=self.lines_tree.yview)
        self.lines_tree.configure(yscrollcommand=vsb.set)
        self.lines_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        meta = tk.Frame(lines_body, bg=COLOR_CARD)
        meta.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.meta_var = tk.StringVar(value="Select an encounter to preview charges.")
        tk.Label(meta, textvariable=self.meta_var, bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL).pack(
            anchor="w"
        )

    # -----------------------------------------------------------------
    # Package deals panel (Phase 5)
    # -----------------------------------------------------------------

    def _build_packages_panel(self, parent: tk.Frame) -> None:
        card, body = make_card(parent, "Package deals", "Visit packages · prepaid plans")
        card.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        # Top action row (row 0): Package Deals checkout — fully independent of
        # the Cash checkout. Post Visit redeems one visit; Take Payment collects
        # money toward an unpaid package balance. Neither touches cash_ledger.
        actions = tk.Frame(body, bg=COLOR_CARD)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.btn_pkg_post_visit = tk.Button(
            actions, text="Post Visit", command=self._post_visit_to_package,
            bg="#7C3AED", fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=12, pady=6, cursor="hand2",
            state="disabled",
        )
        self.btn_pkg_post_visit.pack(side="left", padx=(0, 8))
        self.btn_pkg_take_payment = tk.Button(
            actions, text="Take Payment", command=self._take_package_payment,
            bg=COLOR_GREEN, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=12, pady=6, cursor="hand2",
            state="disabled",
        )
        self.btn_pkg_take_payment.pack(side="left", padx=(0, 8))
        self.btn_pkg_sell = tk.Button(
            actions, text="Sell package", command=self._sell_package_from_panel,
            bg="#0D9488", fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=12, pady=6, cursor="hand2",
            state="disabled",
        )
        self.btn_pkg_sell.pack(side="left", padx=(0, 8))
        tk.Button(
            actions, text="Catalog editor", command=self._open_catalog_editor,
            bg=COLOR_CARD, fg=COLOR_ACCENT, relief="flat",
            font=FONT_BASE_BOLD,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=12, pady=6, cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        self.btn_pkg_refresh = tk.Button(
            actions, text="Refresh", command=self._refresh_packages_panel,
            bg=COLOR_CARD, fg=COLOR_TEXT, relief="flat",
            font=FONT_BASE,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=10, pady=6, cursor="hand2",
        )
        self.btn_pkg_refresh.pack(side="left", padx=(0, 8))
        # Per-stream Receipt folder button — shows ONLY package contracts and
        # statements, never cash or PI receipts. Opens billing/receipts/package/.
        self.btn_pkg_receipt_folder = tk.Button(
            actions, text="Receipt folder",
            command=lambda: self._show_receipt_folder(stream="package"),
            bg=COLOR_CARD, fg=COLOR_ACCENT, relief="flat",
            font=FONT_BASE_BOLD,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=12, pady=6, cursor="hand2",
            state="disabled",
        )
        self.btn_pkg_receipt_folder.pack(side="left")

        # Reconciliation banner (row 1 — grid_forget'd when not needed)
        self.pkg_reconcile_var = tk.StringVar(value="")
        self.pkg_reconcile_label = tk.Label(
            body, textvariable=self.pkg_reconcile_var,
            bg="#FEF3C7", fg="#92400E", font=FONT_SMALL,
            padx=10, pady=6, anchor="w", justify="left", wraplength=900,
        )

        # Patient summary — single horizontal strip across the full width (row 2)
        summary_wrap = tk.Frame(
            body, bg="#F8FAFC",
            highlightbackground=COLOR_BORDER, highlightthickness=1,
        )
        summary_wrap.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        tk.Label(
            summary_wrap, text="Patient summary",
            bg="#F8FAFC", fg=COLOR_MUTED, font=FONT_SMALL,
        ).pack(anchor="w", padx=10, pady=(6, 0))
        self.pkg_summary_var = tk.StringVar(value="Select a patient to see package summary.")
        tk.Label(
            summary_wrap, textvariable=self.pkg_summary_var,
            bg="#F8FAFC", fg=COLOR_TEXT, font=FONT_BASE,
            justify="left", anchor="w",
        ).pack(fill="x", anchor="w", padx=10, pady=(2, 6))

        # Packages tree — full width (row 3, expands vertically)
        tree_wrap = tk.Frame(body, bg=COLOR_BORDER, padx=1, pady=1)
        tree_wrap.grid(row=3, column=0, sticky="nsew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)
        cols = ("name", "status", "used", "remaining", "value", "deferred", "expires")
        self.pkg_tree = ttk.Treeview(
            tree_wrap, columns=cols, show="headings", height=10, selectmode="browse",
        )
        # Tighter widths so the row fits typical panel sizes; horizontal
        # scrollbar below handles narrow windows so no column is ever clipped.
        for col, title, w, anchor, stretch, minw in [
            ("name",      "Package",  200, "w",      True,  140),
            ("status",    "Status",    80, "center", False,  70),
            ("used",      "Used",      50, "center", False,  46),
            ("remaining", "Left",      50, "center", False,  46),
            ("value",     "$/visit",   80, "e",      False,  72),
            ("deferred",  "Deferred",  95, "e",      False,  86),
            ("expires",   "Expires",  100, "center", False,  90),
        ]:
            self.pkg_tree.heading(col, text=title)
            self.pkg_tree.column(col, width=w, anchor=anchor, stretch=stretch, minwidth=minw)
        pkg_vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.pkg_tree.yview)
        pkg_hsb = ttk.Scrollbar(tree_wrap, orient="horizontal", command=self.pkg_tree.xview)
        self.pkg_tree.configure(yscrollcommand=pkg_vsb.set, xscrollcommand=pkg_hsb.set)
        self.pkg_tree.grid(row=0, column=0, sticky="nsew")
        pkg_vsb.grid(row=0, column=1, sticky="ns")
        pkg_hsb.grid(row=1, column=0, sticky="ew")
        self.pkg_tree.bind("<Double-Button-1>", lambda _e: self._open_selected_package_detail())

        # Per-row actions (row 4)
        pkg_actions = tk.Frame(body, bg=COLOR_CARD)
        pkg_actions.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.btn_pkg_detail = tk.Button(
            pkg_actions, text="View detail", command=self._open_selected_package_detail,
            bg=COLOR_CARD, fg=COLOR_ACCENT, relief="flat",
            font=FONT_BASE_BOLD,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=10, pady=4, cursor="hand2", state="disabled",
        )
        self.btn_pkg_detail.pack(side="left", padx=(0, 6))
        self.btn_pkg_refund = tk.Button(
            pkg_actions, text="Refund…", command=self._refund_selected_package,
            bg=COLOR_RED, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=10, pady=4, cursor="hand2",
            state="disabled",
        )
        self.btn_pkg_refund.pack(side="left", padx=(0, 6))
        self.btn_pkg_cancel = tk.Button(
            pkg_actions, text="Cancel (forfeit)", command=self._cancel_selected_package,
            bg=COLOR_CARD, fg=COLOR_RED, relief="flat",
            font=FONT_BASE,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=10, pady=4, cursor="hand2", state="disabled",
        )
        self.btn_pkg_cancel.pack(side="left")

        self.pkg_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_pkg_tree_select())

    def _refresh_packages_panel(self) -> None:
        # Tree contents
        if not hasattr(self, "pkg_tree"):
            return
        self.pkg_tree.delete(*self.pkg_tree.get_children())
        folder = (self.active_patient or {}).get("folder") or ""
        if not folder:
            self.pkg_summary_var.set("Select a patient on Documents first.")
            self.btn_pkg_sell.configure(state="disabled")
            self._set_pkg_row_buttons(False)
            self.pkg_reconcile_label.grid_forget()
            return

        # Hide Sell / Post Visit / Take Payment buttons on PI-only patients
        # (Package deals are out of scope for PI cases by design).
        is_pi = determine_payer_mode(folder) == "pi"
        self.btn_pkg_sell.configure(state="disabled" if is_pi else "normal")
        if hasattr(self, "btn_sell_package"):
            self.btn_sell_package.configure(state="disabled" if is_pi else "normal")

        # Reconciliation banner
        rec = reconcile_pending_operations(folder)
        if not rec.get("ok"):
            parts = []
            if rec.get("orphan_redemptions"):
                parts.append(
                    f"{len(rec['orphan_redemptions'])} package redemption(s) without "
                    "matching cash-ledger adjustment"
                )
            if rec.get("orphan_adjustments"):
                parts.append(
                    f"{len(rec['orphan_adjustments'])} ledger adjustment(s) without "
                    "matching package redemption"
                )
            if rec.get("stale_journal"):
                parts.append("a write-ahead journal entry from a prior incomplete operation")
            msg = (
                "⚠ Reconciliation: detected "
                + "; ".join(parts)
                + ". Open the affected packages in View detail to inspect."
            )
            self.pkg_reconcile_var.set(msg)
            self.pkg_reconcile_label.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        else:
            self.pkg_reconcile_label.grid_forget()

        # Patient summary — horizontal one-liner so dollar values are never truncated.
        # Math is COMPLETELY isolated from cash math: these numbers come only from
        # packages.json (purchases, payments, redemptions, refunds), never from
        # cash_ledger.json or pi_ledger.json.
        events = load_package_log(folder).get("events") or []
        agg = aggregate_revenue(events)
        active_count = sum(1 for s in states_for_patient(events) if is_redeemable(s))
        all_states = states_for_patient(events)
        unpaid_count = sum(
            1 for s in all_states if float(s.get("purchase_balance_due") or 0.0) > 0.01
        )
        summary = (
            f"Active: {active_count}   ·   "
            f"Contracted: ${agg['package_contracted']:,.2f}   ·   "
            f"Collected: ${agg['package_collections']:,.2f}   ·   "
            f"Owed: ${agg['package_outstanding']:,.2f}   ·   "
            f"Earned: ${agg['package_earned']:,.2f}   ·   "
            f"Refunded: ${agg['package_refunded']:,.2f}   ·   "
            f"Deferred: ${agg['package_deferred']:,.2f}"
        )
        if is_pi:
            summary += "      (PI patient — package sales disabled)"
        self.pkg_summary_var.set(summary)

        # Enable Post Visit / Take Payment based on patient + visit state.
        self._update_package_action_buttons(
            folder=folder,
            is_pi=is_pi,
            active_count=active_count,
            unpaid_count=unpaid_count,
        )

        states = states_for_patient(events)
        if not states:
            self.pkg_tree.insert(
                "", "end",
                values=("(No packages yet — click Sell package to start)", "", "", "", "", "", ""),
            )
            self._set_pkg_row_buttons(False)
            return
        for s in states:
            purchase = s.get("purchase") or {}
            iid = s.get("package_id") or ""
            self.pkg_tree.insert(
                "", "end", iid=iid,
                values=(
                    purchase.get("name") or "",
                    status_label(s.get("status") or ""),
                    int(s.get("visits_used") or 0),
                    int(s.get("visits_remaining") or 0),
                    f"${float(purchase.get('prorated_value_per_visit') or 0):,.2f}",
                    f"${float(s.get('deferred_revenue_remaining') or 0):,.2f}",
                    purchase.get("expiration_date") or "—",
                ),
            )
        self._set_pkg_row_buttons(False)

    def _update_package_action_buttons(
        self,
        *,
        folder: str = "",
        is_pi: bool | None = None,
        active_count: int | None = None,
        unpaid_count: int | None = None,
    ) -> None:
        """
        Update Post Visit / Take Payment button enabled state without rebuilding
        the package tree. Safe to call from _select_visit on every click.
        """
        if not hasattr(self, "btn_pkg_post_visit"):
            return
        folder = folder or ((self.active_patient or {}).get("folder") or "")
        if not folder:
            self.btn_pkg_post_visit.configure(state="disabled")
            self.btn_pkg_take_payment.configure(state="disabled")
            return
        if is_pi is None:
            is_pi = determine_payer_mode(folder) == "pi"
        if active_count is None or unpaid_count is None:
            events = load_package_log(folder).get("events") or []
            all_states = states_for_patient(events)
            if active_count is None:
                active_count = sum(1 for s in all_states if is_redeemable(s))
            if unpaid_count is None:
                unpaid_count = sum(
                    1 for s in all_states
                    if float(s.get("purchase_balance_due") or 0.0) > 0.01
                )
        visit_path = (self._selected_visit or {}).get("path") or ""
        can_post = (
            not is_pi
            and active_count > 0
            and bool(visit_path)
            and not is_encounter_posted(folder, visit_path)
            and not is_encounter_pi_posted(folder, visit_path)
            and not is_encounter_package_posted(folder, visit_path)
        )
        self.btn_pkg_post_visit.configure(state="normal" if can_post else "disabled")
        self.btn_pkg_take_payment.configure(
            state="normal" if (not is_pi and unpaid_count > 0) else "disabled"
        )

    def _set_pkg_row_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (self.btn_pkg_detail, self.btn_pkg_refund, self.btn_pkg_cancel):
            btn.configure(state=state)

    def _on_pkg_tree_select(self) -> None:
        sel = self.pkg_tree.selection()
        if not sel:
            self._set_pkg_row_buttons(False)
        else:
            self._set_pkg_row_buttons(True)
        if self._billing_panel == "packages":
            self._refresh_receipt_preview()
        else:
            self._update_pdf_button()

    def _selected_package_id(self) -> str:
        sel = self.pkg_tree.selection()
        return sel[0] if sel else ""

    def _sell_package_from_panel(self) -> None:
        self._open_sell_package_dialog(initial_objectives="")

    def _sell_package_from_cash(self) -> None:
        if not self.active_patient or not self.active_patient.get("folder"):
            return
        folder = self.active_patient.get("folder") or ""
        if determine_payer_mode(folder) == "pi":
            messagebox.showinfo(
                "PI patient",
                "Package deals are for cash patients. PI cases use the PI ledger.",
                parent=self,
            )
            return
        self._open_sell_package_dialog()

    def _open_sell_package_dialog(
        self,
        *,
        initial_visits: int | None = None,
        initial_objectives: str = "",
    ) -> None:
        if not self.active_patient or not self.active_patient.get("folder"):
            messagebox.showinfo("Sell package", "Select a patient first.", parent=self)
            return
        folder = self.active_patient.get("folder") or ""
        SellPackageDialog(
            self,
            patient_root=folder,
            patient_name=self._patient_display_name(),
            recorded_by=self.current_user,
            initial_visits=initial_visits,
            initial_objectives=initial_objectives,
            on_save=lambda _r: self._after_package_change(),
        )

    def _after_package_change(self) -> None:
        self._refresh_account_balance()
        self._refresh_packages_panel()
        if self._current_encounter:
            # Re-render to pick up new suggested redemptions / status
            self._select_visit(self._selected_visit or {})

    def _open_catalog_editor(self) -> None:
        CatalogEditorDialog(self)

    def _open_selected_package_detail(self) -> None:
        pid = self._selected_package_id()
        if not pid or not self.active_patient:
            return
        folder = self.active_patient.get("folder") or ""
        PackageDetailDialog(
            self,
            patient_root=folder,
            package_id=pid,
            patient_name=self._patient_display_name(),
        )

    def _post_visit_to_package(self) -> None:
        """
        Package deals checkout — Post Visit. Applies the currently selected
        visit to an active package (redeems one visit). Does NOT touch the
        cash ledger; package money is fully separate from cash money.
        """
        if not self.active_patient:
            messagebox.showinfo("Post Visit", "Select a patient on Documents first.", parent=self)
            return
        if not self._selected_visit or not self._selected_visit.get("path"):
            messagebox.showinfo(
                "Post Visit",
                "Select a visit in the Encounters list (left side) first.",
                parent=self,
            )
            return
        folder = self.active_patient.get("folder") or ""
        path = self._selected_visit.get("path") or ""
        if determine_payer_mode(folder) == "pi":
            messagebox.showinfo(
                "PI patient",
                "Package deals are for cash patients. PI cases use the PI ledger.",
                parent=self,
            )
            return
        PackagePostVisitDialog(
            self,
            patient_root=folder,
            exam_path=path,
            patient_name=self._patient_display_name(),
            recorded_by=self.current_user,
            on_save=lambda _r: self._after_package_visit_post(),
        )

    def _after_package_visit_post(self) -> None:
        # Refresh the encounters list so the row picks up its new purple tint
        # + Pckg$ badge, then re-render the selected visit and the package panel.
        keep_path = (self._selected_visit or {}).get("path") or ""
        self._load_visits()
        self._reselect_visit_by_path(keep_path)
        self._refresh_packages_panel()
        self._refresh_receipt_preview()

    def _take_package_payment(self) -> None:
        """
        Package deals checkout — Take Payment. Records a payment toward a
        package's outstanding contract balance. Writes only to packages.json
        (no cash-ledger impact).
        """
        if not self.active_patient:
            messagebox.showinfo("Take Payment", "Select a patient on Documents first.", parent=self)
            return
        folder = self.active_patient.get("folder") or ""
        if determine_payer_mode(folder) == "pi":
            messagebox.showinfo(
                "PI patient",
                "Package deals are for cash patients. PI cases use the PI ledger.",
                parent=self,
            )
            return
        preselect = self._selected_package_id()
        PackageTakePaymentDialog(
            self,
            patient_root=folder,
            patient_name=self._patient_display_name(),
            recorded_by=self.current_user,
            preselect_package_id=preselect,
            on_save=lambda _r: self._after_package_change(),
        )

    def _refund_selected_package(self) -> None:
        pid = self._selected_package_id()
        if not pid or not self.active_patient:
            return
        folder = self.active_patient.get("folder") or ""
        RefundPackageDialog(
            self,
            patient_root=folder,
            package_id=pid,
            recorded_by=self.current_user,
            on_save=lambda _r: self._after_package_change(),
        )

    def _cancel_selected_package(self) -> None:
        pid = self._selected_package_id()
        if not pid or not self.active_patient:
            return
        folder = self.active_patient.get("folder") or ""
        CancelPackageDialog(
            self,
            patient_root=folder,
            package_id=pid,
            recorded_by=self.current_user,
            on_save=lambda _r: self._after_package_change(),
        )

    def _build_wip_panel(
        self, parent: tk.Frame, title: str, *, stream: str = ""
    ) -> None:
        card, body = make_card(parent, title)
        card.pack(fill="both", expand=True)
        tk.Label(
            body,
            text="Placeholder: Work in Progress",
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            font=FONT_SECTION,
        ).pack(pady=(24, 8))
        tk.Label(
            body,
            text="This section will be built in a future release.",
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            font=FONT_BASE,
        ).pack(pady=(0, 16))
        # Each WIP stream still gets its own Receipt folder button so the user
        # can drop EOBs / membership statements into the right subfolder
        # manually, and so the structure is visible from day one.
        if stream:
            btn = tk.Button(
                body,
                text="Receipt folder",
                command=lambda s=stream: self._show_receipt_folder(stream=s),
                bg=COLOR_CARD,
                fg=COLOR_ACCENT,
                relief="flat",
                font=FONT_BASE_BOLD,
                highlightthickness=1,
                highlightbackground=COLOR_BORDER,
                padx=14,
                pady=6,
                cursor="hand2",
                state="disabled",
            )
            btn.pack(pady=(0, 24))
            # Track these so they enable/disable with the patient selection.
            attr = f"btn_{stream}_receipt_folder_wip"
            setattr(self, attr, btn)
            if not hasattr(self, "_wip_receipt_buttons"):
                self._wip_receipt_buttons = []
            self._wip_receipt_buttons.append(btn)

    def _set_receipt_preview_text(self, text: str) -> None:
        self.receipt_preview.configure(state="normal")
        self.receipt_preview.delete("1.0", "end")
        self.receipt_preview.insert("1.0", text or "")
        self.receipt_preview.configure(state="disabled")
        self._update_pdf_button()

    def _pdf_kind_for_preview(self) -> str:
        """'cash', 'pi', 'package', or '' when PDF generation isn't available."""
        if not self.active_patient or not self.active_patient.get("folder"):
            return ""
        if self._billing_panel == "packages":
            return "package" if self._selected_package_id() else ""
        if self._billing_panel == "pi":
            if determine_payer_mode(self.active_patient.get("folder")) != "pi":
                return ""
            return "pi"
        posted = self._posted_encounter
        if posted and posted.get("status") == "posted":
            return "cash"
        return ""

    def _update_pdf_button(self) -> None:
        if not hasattr(self, "btn_create_pdf"):
            return
        if not _BILLING_PDF_OK:
            self.btn_create_pdf.configure(state="disabled")
            self.pdf_hint_var.set("Install reportlab for PDF")
            return
        kind = self._pdf_kind_for_preview()
        if kind == "cash":
            self.btn_create_pdf.configure(state="normal")
            self.pdf_hint_var.set("Cash receipt PDF")
        elif kind == "pi":
            self.btn_create_pdf.configure(state="normal")
            self.pdf_hint_var.set("PI case statement PDF")
        elif kind == "package":
            self.btn_create_pdf.configure(state="normal")
            self.pdf_hint_var.set("Package contract PDF")
        else:
            self.btn_create_pdf.configure(state="disabled")
            self.pdf_hint_var.set("")

    def _create_pdf_from_preview(self) -> None:
        kind = self._pdf_kind_for_preview()
        if not kind:
            messagebox.showinfo(
                "Create PDF",
                "Nothing to print yet.\n"
                "Post a visit (cash), switch to the PI ledger, "
                "or select a package on the Package deals tab.",
            )
            return
        folder = self.active_patient.get("folder") or ""
        name = self._patient_display_name()
        try:
            if kind == "cash":
                out = build_cash_receipt_to_receipts(
                    folder,
                    patient_name=name,
                    posted=self._posted_encounter or {},
                    payment=self._receipt_payment_for_current_visit(),
                )
            elif kind == "package":
                pid = self._selected_package_id()
                if not pid:
                    messagebox.showinfo(
                        "Create PDF",
                        "Select a package row first.",
                    )
                    return
                out = build_contract_pdf(
                    folder,
                    patient_name=name,
                    package_id=pid,
                )
            else:
                out = build_pi_case_to_receipts(folder, patient_name=name)
        except RuntimeError as e:
            messagebox.showerror("Create PDF", str(e))
            return
        except Exception as e:
            messagebox.showerror("Create PDF", f"Could not create PDF:\n{e}")
            return
        try:
            os.startfile(str(out))  # type: ignore[attr-defined]
        except OSError:
            pass
        messagebox.showinfo("Create PDF", f"PDF saved to:\n{out}")

    def _receipt_payment_for_current_visit(self) -> dict | None:
        """Last payment only if it belongs to the posted encounter being viewed."""
        pay = self._last_payment
        posted = self._posted_encounter
        if not pay or not posted:
            return None
        enc_id = posted.get("encounter_id") or ""
        if enc_id and pay.get("encounter_id") == enc_id:
            return pay
        exam_path = posted.get("exam_path") or ""
        if exam_path and str(pay.get("exam_path") or "") == str(Path(exam_path).resolve()):
            return pay
        return None

    def _refresh_receipt_preview(self) -> None:
        if not self.active_patient:
            self._set_receipt_preview_text("Select a patient on Documents first.")
            return
        if self._billing_panel == "packages":
            self._refresh_package_document_preview()
            return
        if self._billing_panel == "pi":
            self._refresh_pi_document_preview()
            return
        self._refresh_cash_receipt_preview()

    def _refresh_package_document_preview(self) -> None:
        folder = (self.active_patient or {}).get("folder") or ""
        if not folder:
            self._set_receipt_preview_text("No patient folder.")
            return
        pid = self._selected_package_id()
        if not pid:
            self._set_receipt_preview_text(
                "Select a package row above to preview its details.\n\n"
                "When a package is selected this pane will show the plan name, "
                "pricing, visits used vs. remaining, deferred revenue, expiration, "
                "covered CPT codes, therapeutic objectives, and the full event log "
                "(redemptions, refunds, cancellations).\n\n"
                "Use  Create PDF  (above right) to generate the signed Contract PDF.\n"
                "For the itemized Statement of Account PDF, click  View detail  "
                "below the tree."
            )
            return
        events = all_events_for_package(folder, pid)
        if not events:
            self._set_receipt_preview_text(
                "No events found for the selected package.\n"
                "(The row may belong to a stale view — click Refresh.)"
            )
            return
        state = compute_package_state(events)
        purchase = state.get("purchase") or {}

        line_w = 56
        sep = "-" * line_w
        title_sep = "=" * line_w

        lines: list[str] = []
        plan_name = (purchase.get("name") or "Package").upper()
        lines.append(f"PACKAGE  {plan_name}")
        lines.append(title_sep)
        lines.append(f"Patient        : {self._patient_display_name()}")
        lines.append(f"Package ID     : {pid}")
        lines.append(f"Status         : {status_label(state.get('status') or '')}")
        lines.append(f"Purchase date  : {purchase.get('purchase_date') or '—'}")
        lines.append(f"Expiration     : {purchase.get('expiration_date') or '(none)'}")
        exp_days = state.get("expires_in_days")
        if isinstance(exp_days, int):
            if exp_days < 0:
                lines.append(f"                 (expired {abs(exp_days)} day(s) ago)")
            else:
                lines.append(f"                 ({exp_days} day(s) until expiration)")
        lines.append("")

        lines.append("PRICING")
        lines.append(sep)
        lines.append(
            f"Purchase price : ${float(purchase.get('purchase_price') or 0):>10,.2f}"
        )
        lines.append(
            f"Per-visit value: ${float(purchase.get('prorated_value_per_visit') or 0):>10,.2f}"
        )
        lines.append(
            f"Visits granted : {int(purchase.get('total_visits') or 0):>10d}"
        )
        lines.append("")

        # PAYMENT STATUS — explicit "what was paid", "what's still owed", and a
        # clear PAID IN FULL / BALANCE REMAINING marker so the user never has
        # to derive it from purchase_price minus amount_paid.
        amount_paid = float(state.get("amount_paid") or 0)
        balance_due = float(state.get("purchase_balance_due") or 0)
        lines.append("PAYMENT STATUS")
        lines.append(sep)
        lines.append(f"Amount paid    : ${amount_paid:>10,.2f}")
        if state.get("is_paid_in_full"):
            lines.append(f"Balance        : {'PAID IN FULL':>11s}")
        else:
            lines.append(
                f"Balance        : ${balance_due:>10,.2f}   (remaining to pay)"
            )
        lines.append("")

        lines.append("USAGE  (derived from event log)")
        lines.append(sep)
        lines.append(
            f"Visits used    : {int(state.get('visits_used') or 0):>10d}"
        )
        lines.append(
            f"Visits left    : {int(state.get('visits_remaining') or 0):>10d}"
        )
        lines.append(
            f"Earned revenue : ${float(state.get('value_recognized') or 0):>10,.2f}"
        )
        lines.append(
            f"Refunds paid   : ${float(state.get('refund_paid') or 0):>10,.2f}"
        )
        lines.append(
            f"Deferred       : ${float(state.get('deferred_revenue_remaining') or 0):>10,.2f}"
        )
        lines.append("")

        whitelist = purchase.get("cpt_whitelist") or []
        if whitelist:
            lines.append("COVERED CPT CODES")
            lines.append(sep)
            lines.append("  " + ", ".join(str(c) for c in whitelist))
            lines.append("")

        objectives = (purchase.get("therapeutic_objectives") or "").strip()
        if objectives:
            lines.append("THERAPEUTIC OBJECTIVES")
            lines.append(sep)
            for chunk in objectives.splitlines() or [objectives]:
                lines.append(chunk)
            lines.append("")

        redemptions = state.get("redemptions") or []
        if redemptions:
            lines.append(f"VISITS USED  ({len(redemptions)})")
            lines.append(sep)
            for r in redemptions:
                dos = r.get("date_of_service") or (r.get("timestamp") or "")[:10] or "—"
                cpts_list = r.get("cpts_redeemed") or []
                if cpts_list:
                    cpt_label = "CPTs " + ", ".join(str(c) for c in cpts_list)
                else:
                    cpt_label = f"CPT {r.get('cpt_redeemed') or ''}".rstrip()
                val = float(r.get("value_recognized") or 0)
                lines.append(
                    f"  {dos:<12}  {cpt_label:<28}  recognized ${val:>8,.2f}"
                )
            lines.append("")

        refunds = state.get("refunds") or []
        if refunds:
            lines.append(f"REFUNDS  ({len(refunds)})")
            lines.append(sep)
            for r in refunds:
                dos = r.get("refund_date") or (r.get("timestamp") or "")[:10] or "—"
                amt = float(r.get("amount") or 0)
                strategy = r.get("refund_strategy") or "—"
                method = r.get("method") or ""
                lines.append(
                    f"  {dos:<12}  ${amt:>10,.2f}  via {method:<8}  ({strategy})"
                )
            lines.append("")

        cancellations = state.get("cancellations") or []
        if cancellations:
            lines.append(f"CANCELLATIONS  ({len(cancellations)})")
            lines.append(sep)
            for c in cancellations:
                dos = (c.get("timestamp") or "")[:10] or "—"
                reason = (c.get("reason") or c.get("memo") or "—").strip()
                lines.append(f"  {dos:<12}  reason: {reason[:38]}")
            lines.append("")

        lines.append("---")
        lines.append(
            "Click  Create PDF  (above right) to generate the signed Contract PDF."
        )
        lines.append(
            "Click  View detail (below tree) for the Statement of Account PDF "
            "and full event inspector."
        )

        self._set_receipt_preview_text("\n".join(lines))

    def _refresh_cash_receipt_preview(self) -> None:
        if not self._selected_visit:
            self._set_receipt_preview_text(
                "Select a visit for cash receipt preview.\n\n"
                "Switch to PI ledger for case settlement documents."
            )
            return
        folder = self.active_patient.get("folder") or ""
        path = self._selected_visit.get("path") or ""
        # Package-posted visits never appear on cash receipts (cash math is fully
        # separate from package money). Tell the user so they don't think it's a bug.
        if folder and path and is_encounter_package_posted(folder, path):
            self._set_receipt_preview_text(
                "This visit was posted to a Package Deal — it does not appear "
                "on cash receipts.\n\n"
                "Switch to the Package deals tab to view the package contract, "
                "statement, and event log."
            )
            return
        posted = load_posted_encounter(folder, path) if folder and path else None
        if not posted or posted.get("status") != "posted":
            self._set_receipt_preview_text(
                "Receipt preview appears after you post this visit to the cash ledger.\n\n"
                "Use Cash checkout → Post cash, then take payment if needed."
            )
            return
        bal = compute_cash_balance(folder)["balance_due"] if folder else 0.0
        text = build_receipt_text(
            patient_name=self._patient_display_name(),
            posted=posted,
            payment=self._receipt_payment_for_current_visit(),
            account_balance=bal,
            patient_root=folder,
        )
        self._set_receipt_preview_text(text)

    def _refresh_pi_document_preview(self) -> None:
        folder = self.active_patient.get("folder") or ""
        if not folder:
            self._set_receipt_preview_text("No patient folder.")
            return
        if determine_payer_mode(folder) != "pi":
            self._set_receipt_preview_text(
                "Patient is not typed PI/Auto.\n\n"
                "Use Cash checkout for desk payment receipts."
            )
            return

        docs = list_billing_documents(folder)
        for doc in docs:
            stem = doc.path.stem
            if stem.startswith("receipt_"):
                continue
            # The preview pane only renders text. PDFs (cash/package/pi)
            # are still listed in the Receipt folder dialog and openable
            # there — they just can't be inlined here.
            if doc.path.suffix.lower() != ".txt":
                continue
            if stem.startswith(("settlement_", "pi_case_summary_", "pi_cover_sheet_")) or doc.kind in (
                "export",
                "packet",
            ):
                try:
                    body = doc.path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue  # fall through to the next candidate
                except OSError as e:
                    self._set_receipt_preview_text(f"Could not read {doc.path.name}:\n{e}")
                    return
                self._set_receipt_preview_text(f"{doc.label}\n{'=' * 42}\n\n{body}")
                return

        bal = compute_pi_balance(folder)
        if bal["total_charges"] > 0.01 or is_pi_case_settled(folder):
            try:
                live = build_case_summary_text(
                    patient_root=folder,
                    patient_name=self._patient_display_name(),
                )
            except Exception as e:
                self._set_receipt_preview_text(f"Could not build case summary:\n{e}")
                return
            self._set_receipt_preview_text(
                "Live preview (not saved yet):\n"
                f"{'=' * 42}\n\n"
                f"{live}\n\n"
                "---\n"
                "Save a copy with Record settlement or Attorney packet → Build packet folder."
            )
            return

        self._set_receipt_preview_text(
            "Post visits to the PI case, then use Record settlement or Attorney packet.\n\n"
            "Saved summaries and settlement receipts appear here after you save them."
        )

    def _refresh_patient_header(self) -> None:
        if not self.active_patient:
            self.billing_for_var.set("Billing for: —")
            self.balance_var.set("No patient selected — open Documents and select a patient")
            self._refresh_receipt_preview()
            self._set_receipt_folder_enabled()
            if hasattr(self, "pkg_tree"):
                self._refresh_packages_panel()
            return
        self.billing_for_var.set(f"Billing for: {self._patient_display_name()}")
        folder = self.active_patient.get("folder")
        if folder:
            self._refresh_account_balance()
            self._refresh_pi_header()
        else:
            self.balance_var.set("")
            self.pi_balance_var.set("")
            self.pi_case_var.set("")
        self._refresh_receipt_preview()
        self._set_receipt_folder_enabled()
        if hasattr(self, "pkg_tree"):
            self._refresh_packages_panel()
        self._persist_shell_patient()

    def _set_receipt_folder_enabled(self) -> None:
        folder = (self.active_patient or {}).get("folder") or ""
        state = "normal" if folder else "disabled"
        self.btn_receipt_folder.configure(state=state)
        self.btn_pi_receipt_folder.configure(state=state)
        if hasattr(self, "btn_pkg_receipt_folder"):
            self.btn_pkg_receipt_folder.configure(state=state)
        for btn in getattr(self, "_wip_receipt_buttons", []) or []:
            try:
                btn.configure(state=state)
            except tk.TclError:
                pass

    def _refresh_pi_header(self) -> None:
        folder = (self.active_patient or {}).get("folder") or ""
        if not folder or determine_payer_mode(folder) != "pi":
            self.pi_balance_var.set("")
            self.pi_case_var.set("")
            self._set_pi_buttons_enabled(False)
            return
        pid = (self.active_patient or {}).get("patient_id") or ""
        case = load_or_create_pi_case(folder, patient_id=pid)
        bal = compute_pi_balance(folder)
        atty = (case.get("attorney") or {}).get("name") or "—"
        self.pi_balance_var.set(
            f"PI case balance: ${bal['balance_due']:,.2f}  "
            f"(charges ${bal['total_charges']:,.2f} · "
            f"paid ${bal['total_payments']:,.2f} · "
            f"adj ${bal['total_adjustments']:,.2f})"
        )
        self.pi_case_var.set(
            f"DOI {(case.get('date_of_injury') or '—')}  ·  "
            f"{case_status_label(case.get('case_status') or 'active')}  ·  "
            f"Attorney: {atty}"
        )
        self._set_pi_buttons_enabled(True)
        self._refresh_pi_settlement_button(folder, case, bal)

    def _refresh_pi_settlement_button(self, folder: str, case: dict, bal: dict) -> None:
        settled = (case.get("case_status") or "").strip().lower() == "settled"
        can_settle = bal["balance_due"] > 0.01 and not settled
        self.btn_record_settlement.configure(state="normal" if can_settle else "disabled")

    def _set_pi_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (
            self.btn_post_pi,
            self.btn_export_case,
            self.btn_closeout,
            self.btn_edit_case,
            self.btn_pi_adjust,
        ):
            btn.configure(state=state)
        if not enabled:
            self.btn_pi_pay.configure(state="disabled")
            self.btn_record_settlement.configure(state="disabled")
            self.btn_pi_receipt_folder.configure(state="disabled")

    def _refresh_account_balance(self) -> None:
        if not self.active_patient:
            self.balance_var.set("")
            return
        folder = self.active_patient.get("folder")
        if not folder:
            return
        cash_bal = compute_cash_balance(folder)
        if determine_payer_mode(folder) == "pi":
            pi_bal = compute_pi_balance(folder)
            text = (
                f"Account balance: ${pi_bal['balance_due']:,.2f}  "
                f"(PI case · charges ${pi_bal['total_charges']:,.2f} · "
                f"paid ${pi_bal['total_payments']:,.2f} · "
                f"adj ${pi_bal['total_adjustments']:,.2f})"
            )
            if cash_bal["total_charges"] > 0.01 or cash_bal["total_payments"] > 0.01:
                text += (
                    f"  ·  Cash desk: ${cash_bal['balance_due']:,.2f}"
                )
            self.balance_var.set(text)
            return
        self.balance_var.set(
            f"Account balance: ${cash_bal['balance_due']:,.2f}  "
            f"(charges ${cash_bal['total_charges']:,.2f} · "
            f"payments ${cash_bal['total_payments']:,.2f})"
        )

    def _paint_visit_row_widget(self, widget: tk.Misc, bg: str) -> None:
        """Update row backgrounds; leave CASH/PI badge colors unchanged."""
        if isinstance(widget, (tk.Frame, tk.Label)):
            try:
                if widget.cget("bg") in _VISIT_ROW_SYNC_BGS:
                    widget.configure(bg=bg)
            except tk.TclError:
                pass
        if isinstance(widget, tk.Frame):
            for child in widget.winfo_children():
                self._paint_visit_row_widget(child, bg)

    def _paint_visit_row(
        self,
        row: tk.Frame,
        bg: str,
        *,
        border_color: str | None = None,
        border_thickness: int | None = None,
    ) -> None:
        row.configure(bg=bg)
        if border_color is not None:
            row.configure(highlightbackground=border_color)
        if border_thickness is not None:
            row.configure(highlightthickness=border_thickness)
        self._paint_visit_row_widget(row, bg)

    def _highlight_selected_visit_rows(self) -> None:
        """
        Repaint every visit row to reflect whether it's the active selection.

        Selection is now indicated ONLY by a thicker, bolder border — the
        base background tint (which encodes posting status: yellow=cash,
        purple=package, blue=PI, white=unposted) is preserved so the user
        always sees the card's true posting state at a glance.
        """
        selected_path = (self._selected_visit or {}).get("path") or ""
        for path, row in self._visit_row_by_path.items():
            base_bg = getattr(row, "_row_base_bg", COLOR_VISIT_ROW)
            if path == selected_path:
                self._paint_visit_row(
                    row,
                    base_bg,
                    border_color=getattr(
                        row, "_row_border_selected", COLOR_VISIT_ROW_BORDER_SELECTED,
                    ),
                    border_thickness=VISIT_ROW_BORDER_THICKNESS_SELECTED,
                )
            else:
                self._paint_visit_row(
                    row,
                    base_bg,
                    border_color=getattr(row, "_row_border", COLOR_BORDER),
                    border_thickness=VISIT_ROW_BORDER_THICKNESS,
                )

    def _load_visits(self) -> None:
        for w in self.enc_inner.winfo_children():
            w.destroy()
        self._visits = []
        self._visit_row_by_path = {}
        self._selected_visit = None
        self._clear_detail()

        if not self.active_patient:
            tk.Label(
                self.enc_inner,
                text="Select a patient on the Documents page first.",
                bg=COLOR_CARD,
                fg=COLOR_MUTED,
                font=FONT_BASE,
            ).pack(pady=20)
            return

        folder = Path(self.active_patient.get("folder") or "")
        if not folder.is_dir():
            return

        self._visits = collect_visits_for_patient(folder)
        if not self._visits:
            tk.Label(
                self.enc_inner,
                text="No saved encounters yet.",
                bg=COLOR_CARD,
                fg=COLOR_MUTED,
                font=FONT_BASE,
            ).pack(pady=20)
            return

        for visit in self._visits:
            self._make_visit_row(visit)

    def _row_color_tier(
        self, *, cash_posted: bool, package_posted: bool, pi_posted: bool
    ) -> tuple[str, str, str, str]:
        """
        Return (base_bg, hover_bg, border_color, border_color_selected) for a
        visit row based on which flow(s) it's posted to.

        The selected-border color is a bolder variant of the tier border so the
        active card always has a clearly thicker, darker outline regardless of
        which money stream tinted its background. Package > PI > cash priority
        for the background tint, but the row may show multiple badges if a
        legacy visit was dual-posted.
        """
        if package_posted:
            return (
                COLOR_VISIT_ROW_PACKAGE,
                COLOR_VISIT_ROW_PACKAGE_HOVER,
                COLOR_VISIT_ROW_PACKAGE_BORDER,
                COLOR_VISIT_ROW_PACKAGE_BORDER_SELECTED,
            )
        if pi_posted:
            return (
                COLOR_VISIT_ROW_PI,
                COLOR_VISIT_ROW_PI_HOVER,
                COLOR_VISIT_ROW_PI_BORDER,
                COLOR_VISIT_ROW_PI_BORDER_SELECTED,
            )
        if cash_posted:
            return (
                COLOR_VISIT_ROW_CASH,
                COLOR_VISIT_ROW_CASH_HOVER,
                COLOR_VISIT_ROW_CASH_BORDER,
                COLOR_VISIT_ROW_CASH_BORDER_SELECTED,
            )
        return (
            COLOR_VISIT_ROW,
            COLOR_VISIT_ROW_HOVER,
            COLOR_BORDER,
            COLOR_VISIT_ROW_BORDER_SELECTED,
        )

    def _make_visit_row(self, visit: dict) -> None:
        visit_path = visit.get("path") or ""

        cash_posted = False
        pi_posted = False
        package_posted = False
        if self.active_patient and visit.get("path"):
            folder = self.active_patient.get("folder") or ""
            cash_posted = is_encounter_posted(folder, visit["path"])
            pi_posted = is_encounter_pi_posted(folder, visit["path"])
            package_posted = is_encounter_package_posted(folder, visit["path"])

        base_bg, hover_bg, border_color, border_color_selected = self._row_color_tier(
            cash_posted=cash_posted,
            package_posted=package_posted,
            pi_posted=pi_posted,
        )

        row = tk.Frame(
            self.enc_inner,
            bg=base_bg,
            highlightbackground=border_color,
            highlightthickness=VISIT_ROW_BORDER_THICKNESS,
            cursor="hand2",
        )
        row.pack(fill="x", padx=4, pady=4)
        if visit_path:
            self._visit_row_by_path[visit_path] = row
        # Cache the row's "true" tier colors so hover / selection use them.
        row._row_base_bg = base_bg                          # type: ignore[attr-defined]
        row._row_hover_bg = hover_bg                        # type: ignore[attr-defined]
        row._row_border = border_color                      # type: ignore[attr-defined]
        row._row_border_selected = border_color_selected    # type: ignore[attr-defined]

        exam_name = visit.get("exam_name") or ""
        et = classify_exam_type(exam_name)
        type_color = COLOR_ACCENT if et == "initial" else COLOR_GREEN

        top = tk.Frame(row, bg=base_bg)
        top.pack(pady=(6, 0))
        tk.Label(
            top,
            text=visit.get("exam_date") or "—",
            bg=base_bg,
            fg=COLOR_TEXT,
            font=FONT_BASE_BOLD,
        ).pack(side="left")
        if cash_posted:
            tk.Label(
                top,
                text=" CASH ",
                bg="#DCFCE7",
                fg=COLOR_GREEN,
                font=("Segoe UI", 8, "bold"),
            ).pack(side="left", padx=(6, 0))
        if package_posted:
            tk.Label(
                top,
                text=" Pckg$ ",
                bg=COLOR_VISIT_ROW_PACKAGE_HOVER,
                fg="#6B21A8",
                font=("Segoe UI", 8, "bold"),
            ).pack(side="left", padx=(6, 0))
        if pi_posted:
            tk.Label(
                top,
                text=" PI ",
                bg="#DBEAFE",
                fg="#1D4ED8",
                font=("Segoe UI", 8, "bold"),
            ).pack(side="left", padx=(6, 0))
        tk.Label(
            row,
            text=exam_name,
            bg=base_bg,
            fg=type_color,
            font=FONT_BASE,
        ).pack(anchor="center", padx=8)
        tk.Label(
            row,
            text=visit.get("provider") or "—",
            bg=base_bg,
            fg=COLOR_MUTED,
            font=FONT_SMALL,
        ).pack(anchor="center", padx=8, pady=(0, 6))

        def select(_e=None, v=visit):
            self._select_visit(v)

        for w in (row, *row.winfo_children()):
            w.bind("<Button-1>", select)

        def hover_in(_e=None, r=row, p=visit_path):
            # Hover only tints the background — the border (thin/thick + tier
            # color) stays as `_highlight_selected_visit_rows` set it, so the
            # active card never loses its bold border on hover.
            if (self._selected_visit or {}).get("path") != p:
                self._paint_visit_row(r, r._row_hover_bg)  # type: ignore[attr-defined]

        def hover_out(_e=None, r=row, p=visit_path):
            # Restore the row's true tier-bg; leave border alone for the same
            # reason — selection state is encoded purely in border thickness.
            self._paint_visit_row(
                r,
                r._row_base_bg,  # type: ignore[attr-defined]
            )

        row.bind("<Enter>", hover_in)
        row.bind("<Leave>", hover_out)

    def _select_visit(self, visit: dict) -> None:
        self._selected_visit = visit
        new_path = str(Path(visit.get("path") or "").resolve()) if visit.get("path") else ""
        if self._last_payment and new_path:
            pay_path = str(self._last_payment.get("exam_path") or "")
            if pay_path and pay_path != new_path:
                self._last_payment = None
        self._highlight_selected_visit_rows()
        folder = Path(self.active_patient.get("folder") or "") if self.active_patient else None
        if not folder:
            return
        path = visit.get("path") or ""
        self._posted_encounter = load_posted_encounter(folder, path)
        self._posted_pi_encounter = load_pi_posted_encounter(folder, path)
        self._posted_package_encounter = load_package_posted_encounter(folder, path)

        # One-way tab follow: clicking a posted card switches the billing
        # tab above to the flow that posted it (matches the card's color
        # tier — package=purple > pi=blue > cash=yellow). Unposted/beige
        # cards leave the current tab alone so the user keeps whatever
        # checkout view they were working in.
        if self._posted_package_encounter:
            self._show_billing_panel("packages")
        elif self._posted_pi_encounter:
            self._show_billing_panel("pi")
        elif self._posted_encounter:
            self._show_billing_panel("cash")

        if self._posted_package_encounter:
            enc = self._posted_package_encounter
        elif self._posted_pi_encounter:
            enc = self._posted_pi_encounter
        elif self._posted_encounter:
            enc = self._posted_encounter
        else:
            try:
                enc = load_or_refresh_shadow_encounter(folder, path)
            except Exception as e:
                messagebox.showerror("Billing", f"Could not build charge preview:\n{e}")
                return
            if not enc:
                messagebox.showerror("Billing", f"Exam file not found:\n{path}")
                return
        self._current_encounter = enc
        self._render_encounter(enc)
        self._highlight_selected_visit_rows()
        self._update_package_action_buttons()

    def _rebuild_selected(self) -> None:
        if not self._selected_visit or not self.active_patient:
            messagebox.showinfo("Billing", "Select an encounter first.")
            return
        folder = Path(self.active_patient.get("folder") or "")
        path = self._selected_visit.get("path") or ""
        if is_encounter_posted(folder, path) or is_encounter_pi_posted(folder, path):
            messagebox.showinfo(
                "Already posted",
                "This visit is posted to a ledger. "
                "Charges cannot be refreshed from the chart without voiding (not available yet).",
            )
            return
        try:
            enc = load_or_refresh_shadow_encounter(folder, path, force=True)
            if not enc:
                messagebox.showerror("Billing", f"Exam file not found:\n{path}")
                return
            self._current_encounter = enc
            self._render_encounter(enc)
        except Exception as e:
            messagebox.showerror("Billing", f"Refresh failed:\n{e}")

    def _clear_detail(self) -> None:
        self._current_encounter = None
        self._posted_encounter = None
        self._posted_pi_encounter = None
        self._posted_package_encounter = None
        self.btn_post.configure(state="disabled")
        self.btn_pay.configure(state="disabled")
        self.btn_receipt.configure(state="disabled")
        self.btn_post_pi.configure(state="disabled")
        self.btn_pi_pay.configure(state="disabled")
        self.checkout_status_var.set("Select a visit to begin checkout.")
        self.pi_checkout_status_var.set("Select a visit for PI case posting.")
        for w in self.totals_frame.winfo_children():
            w.destroy()
        self.lines_tree.delete(*self.lines_tree.get_children())
        self._current_warnings = []
        self._refresh_warnings_buttons()
        self.meta_var.set("Select an encounter to preview charges.")
        self._set_receipt_preview_text("Select a visit to preview a receipt.")

    # ------------------------------------------------------------------
    # On-demand "Review warnings" popup (replaces the old inline card)
    # ------------------------------------------------------------------

    def _make_review_warnings_button(
        self,
        parent: tk.Widget,
        *,
        side: str = "left",
        padx: tuple[int, int] = (6, 0),
        pady: int = 4,
    ) -> tk.Button:
        """
        Build and register a "Review warnings" button. The button text +
        background are kept in sync with the current encounter's warning
        count by `_refresh_warnings_buttons()`, so any flow that hosts one
        of these gets the same one-click access the old inline card gave.
        """
        btn = tk.Button(
            parent,
            text="Review warnings",
            command=self._show_warnings_popup,
            bg=COLOR_CARD,
            fg=COLOR_ACCENT,
            relief="flat",
            font=FONT_BASE_BOLD,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            padx=10,
            pady=pady,
            cursor="hand2",
        )
        btn.pack(side=side, padx=padx)
        self._warnings_buttons.append(btn)
        return btn

    def _refresh_warnings_buttons(self) -> None:
        """Sync every registered Review-warnings button to reflect count/level."""
        count = len(self._current_warnings or [])
        has_warn_level = any(
            (w.get("level") or "info") == "warning"
            for w in (self._current_warnings or [])
        )
        if count == 0:
            label = "Review warnings"
            bg = COLOR_CARD
            fg = COLOR_ACCENT
            border = COLOR_BORDER
        else:
            label = f"Review warnings ({count})"
            # Yellow-tinted when there are warnings; soft amber for "warning"
            # level, light cream for info-only.
            bg = "#FEF3C7" if has_warn_level else "#FFFBEB"
            fg = "#92400E" if has_warn_level else COLOR_TEXT
            border = "#F59E0B" if has_warn_level else COLOR_BORDER
        for btn in list(self._warnings_buttons):
            try:
                btn.configure(text=label, bg=bg, fg=fg, highlightbackground=border)
            except tk.TclError:
                # Button got destroyed (e.g., panel rebuilt) — drop it.
                self._warnings_buttons.remove(btn)

    def _show_warnings_popup(self) -> None:
        """
        Open a small modal showing the warnings for the current encounter.
        Closes via Close button, the [X], or Escape.
        """
        win = tk.Toplevel(self)
        win.title("Review warnings")
        win.configure(bg=COLOR_CARD)
        win.transient(self.winfo_toplevel())
        win.geometry("560x340")
        win.minsize(420, 240)

        header = tk.Frame(win, bg=COLOR_CARD)
        header.pack(fill="x", padx=14, pady=(14, 6))
        tk.Label(
            header,
            text="Review warnings",
            bg=COLOR_CARD,
            fg=COLOR_TEXT,
            font=FONT_TITLE,
        ).pack(side="left")
        count = len(self._current_warnings or [])
        sub = "Ready for staff review." if count == 0 else f"{count} item(s) flagged for review."
        tk.Label(
            header,
            text=sub,
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            font=FONT_SMALL,
        ).pack(side="left", padx=(10, 0))

        body = tk.Frame(win, bg=COLOR_CARD)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        text = tk.Text(
            body,
            wrap="word",
            font=FONT_BASE,
            bg="#FFFBEB",
            fg=COLOR_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
        )
        vsb = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=vsb.set)
        text.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        if not self._current_warnings:
            text.insert("end", "No warnings — ready for staff review.")
        else:
            for w in self._current_warnings:
                level = w.get("level") or "info"
                msg = w.get("message") or ""
                prefix = "⚠ " if level == "warning" else "ℹ "
                text.insert("end", prefix + msg + "\n")
        text.configure(state="disabled")

        btn_bar = tk.Frame(win, bg=COLOR_CARD)
        btn_bar.pack(fill="x", padx=14, pady=(0, 14))
        tk.Button(
            btn_bar,
            text="Close",
            command=win.destroy,
            bg=COLOR_ACCENT,
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=18,
            pady=6,
            cursor="hand2",
        ).pack(side="right")

        win.bind("<Escape>", lambda _e: win.destroy())
        win.focus_set()

    def _render_encounter(self, enc: dict) -> None:
        for w in self.totals_frame.winfo_children():
            w.destroy()

        totals = enc.get("totals") or {}
        primary = enc.get("primary_schedule") or "cash"
        cash_t = totals.get("cash", 0)
        pi_t = totals.get("pi_ucr", 0)

        for label, amt, highlight in [
            ("Cash schedule", cash_t, primary == "cash"),
            ("PI / UCR schedule", pi_t, primary == "pi_ucr"),
        ]:
            fr = tk.Frame(self.totals_frame, bg=COLOR_CARD)
            fr.pack(side="left", padx=(0, 24))
            fg = COLOR_ACCENT if highlight else COLOR_TEXT
            tk.Label(fr, text=label, bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL).pack(anchor="w")
            tk.Label(
                fr,
                text=f"${amt:,.2f}",
                bg=COLOR_CARD,
                fg=fg,
                font=("Segoe UI", 20, "bold"),
            ).pack(anchor="w")

        self.lines_tree.delete(*self.lines_tree.get_children())
        dx_all = ", ".join(enc.get("diagnosis_pointers") or []) or "—"
        for ln in enc.get("lines") or []:
            mod = ln.get("modifier_1") or ""
            desc = (ln.get("description") or "")[:48]
            fees = ln.get("fees") or {}
            dx_ptr = ", ".join(ln.get("diagnosis_pointers") or []) or dx_all
            self.lines_tree.insert(
                "",
                "end",
                values=(
                    ln.get("cpt_code") or "",
                    mod,
                    desc,
                    ln.get("units") or 1,
                    dx_ptr,
                    f"{fees.get('cash', 0):.2f}",
                    f"{fees.get('pi_ucr', 0):.2f}",
                ),
            )

        # Cache warnings for the on-demand "Review warnings" popup; refresh
        # each per-flow button so its label/color reflects the current count.
        self._current_warnings = list(enc.get("warnings") or [])
        self._refresh_warnings_buttons()

        exam = enc.get("exam_name") or ""
        dos = enc.get("date_of_service") or "—"
        et = enc.get("exam_type") or "unknown"
        n = len(enc.get("lines") or [])
        status = enc.get("status") or "shadow"
        ledger = enc.get("ledger") or ""
        ledger_tag = f" · {ledger.upper()}" if ledger else ""
        self.meta_var.set(
            f"{exam}  ·  DOS {dos}  ·  Type {et}  ·  {n} line(s)  ·  {status.upper()}{ledger_tag}"
        )
        self._update_checkout_state(enc)
        self._refresh_receipt_preview()

    def _update_checkout_state(self, enc: dict) -> None:
        if not self.active_patient or not self._selected_visit:
            return
        folder = self.active_patient.get("folder") or ""
        path = self._selected_visit.get("path") or ""
        cash_posted = is_encounter_posted(folder, path)
        pi_posted = is_encounter_pi_posted(folder, path)
        payer_pi = determine_payer_mode(folder) == "pi"

        if cash_posted:
            self.btn_post.configure(state="disabled")
            due = encounter_amount_due(folder, path)
            self.btn_pay.configure(state="normal" if due > 0 else "disabled")
            self.btn_receipt.configure(state="normal")
            self.checkout_status_var.set(
                f"Cash posted ${float((load_posted_encounter(folder, path) or {}).get('amount_charged') or 0):,.2f} · "
                f"Visit balance: ${due:,.2f}"
            )
        else:
            self.btn_receipt.configure(state="disabled")
            self.btn_pay.configure(state="disabled")
            self.btn_post.configure(state="normal")
            suggestions = (enc.get("package_meta") or {}).get("suggested_redemptions") or []
            if suggestions and not payer_pi:
                cpts = ", ".join(s.get("cpt") or "" for s in suggestions)
                self.checkout_status_var.set(
                    f"Active package covers {len(suggestions)} line(s) "
                    f"({cpts}) — you'll be prompted on Post cash."
                )
            else:
                self.checkout_status_var.set(
                    "Post cash for same-day desk payment (PI patients can also use PI case ledger)."
                )
        # Sell package button: only meaningful for non-PI patients with a folder
        if hasattr(self, "btn_sell_package"):
            self.btn_sell_package.configure(state="disabled" if payer_pi else "normal")

        if payer_pi:
            self._set_pi_buttons_enabled(True)
            settled = is_pi_case_settled(folder)
            case = load_or_create_pi_case(folder)
            bal = compute_pi_balance(folder)
            self._refresh_pi_settlement_button(folder, case, bal)
            if pi_posted:
                self.btn_post_pi.configure(state="disabled")
                posted_pi = load_pi_posted_encounter(folder, path) or {}
                posted_amt = float(posted_pi.get("amount_charged") or 0)
                if settled:
                    self.btn_pi_pay.configure(state="disabled")
                    self.pi_checkout_status_var.set(
                        f"PI posted ${posted_amt:,.2f} · Case settled — paid in full"
                    )
                else:
                    pi_due = pi_encounter_amount_due(folder, path)
                    self.btn_pi_pay.configure(state="normal" if pi_due > 0 else "disabled")
                    self.pi_checkout_status_var.set(
                        f"PI posted ${posted_amt:,.2f} · Visit balance: ${pi_due:,.2f}"
                    )
            else:
                self.btn_post_pi.configure(state="disabled" if cash_posted or settled else "normal")
                self.btn_pi_pay.configure(state="disabled")
                if cash_posted:
                    self.pi_checkout_status_var.set(
                        "Visit on cash ledger — cannot also post to PI case."
                    )
                elif settled:
                    self.pi_checkout_status_var.set("PI case settled — no new visits can be posted.")
                else:
                    self.pi_checkout_status_var.set(
                        "Review PI/UCR total, then Post to PI case to accumulate for attorney billing."
                    )
        else:
            self.pi_checkout_status_var.set("Patient is cash/self-pay — PI ledger not used.")
            self.btn_post_pi.configure(state="disabled")
            self.btn_pi_pay.configure(state="disabled")

    def _post_charges(self) -> None:
        """
        Cash checkout post. Cash math is fully separated from package money — if
        the doctor wants this visit applied to a package, the user should use
        Package deals → Post Visit instead.
        """
        if not self.active_patient or not self._selected_visit:
            return
        folder = self.active_patient.get("folder") or ""
        path = self._selected_visit.get("path") or ""

        # Refuse cash-post if visit is already package-posted (single-flow rule).
        if is_encounter_package_posted(folder, path):
            messagebox.showinfo(
                "Already posted to package",
                "This visit was already applied to a package deal. Each visit "
                "posts to exactly one flow (cash, package, or PI).",
            )
            return

        force = False
        if determine_payer_mode(folder) == "pi":
            if not messagebox.askyesno(
                "Cash checkout on PI case",
                "This patient is typed as PI/Auto.\n\n"
                "Post charges to today's cash ledger anyway?\n"
                "(Use when the patient pays at the desk today.)",
            ):
                return
            force = True

        self._finalize_post_charges(folder, path, force)

    def _finalize_post_charges(
        self,
        folder: str,
        path: str,
        force: bool,
    ) -> None:
        try:
            posted = post_encounter_to_cash_ledger(
                patient_root=folder,
                exam_path=path,
                posted_by=self.current_user,
                force_cash=force,
                package_redemptions=None,  # cash is pure cash; use Package deals tab for redemptions
            )
        except ValueError as e:
            messagebox.showinfo("Cannot post", str(e))
            return
        except Exception as e:
            messagebox.showerror("Post failed", str(e))
            return
        self._posted_encounter = posted
        self._current_encounter = posted
        self._render_encounter(posted)
        self._refresh_account_balance()
        self._refresh_pi_header()
        if hasattr(self, "pkg_tree"):
            self._refresh_packages_panel()
        self._load_visits()
        messagebox.showinfo(
            "Posted",
            f"Charges posted: ${float(posted.get('amount_charged') or 0):,.2f}\n"
            "You can take a payment or print a receipt next.",
        )

    def _take_payment(self) -> None:
        if not self.active_patient or not self._posted_encounter:
            messagebox.showinfo("Payment", "Post charges for this visit first.")
            return
        folder = self.active_patient.get("folder") or ""
        path = self._posted_encounter.get("exam_path") or ""
        default_amt = encounter_amount_due(folder, path)
        if default_amt <= 0:
            messagebox.showinfo("Payment", "This visit has no balance due.")
            return
        PaymentDialog(
            self,
            default_amount=default_amt,
            on_save=lambda amt, method, pdate: self._apply_payment(amt, method, pdate),
        )

    def _apply_payment(self, amount: float, method: str, payment_date: str) -> None:
        folder = self.active_patient.get("folder") or ""
        posted = self._posted_encounter or {}
        try:
            pay = record_payment(
                patient_root=folder,
                amount=amount,
                method=method,
                payment_date=payment_date,
                encounter_id=posted.get("encounter_id") or "",
                exam_path=posted.get("exam_path") or "",
                recorded_by=self.current_user,
            )
        except Exception as e:
            messagebox.showerror("Payment failed", str(e))
            return
        self._refresh_account_balance()
        self._update_checkout_state(posted)
        self._last_payment = pay
        self._refresh_receipt_preview()
        messagebox.showinfo("Payment recorded", f"${amount:,.2f} ({method}) applied.")
        if messagebox.askyesno("Receipt", "Open full receipt window to save a copy?"):
            self._show_receipt(payment=pay)

    def _show_receipt(self, payment: dict | None = None) -> None:
        if not self.active_patient:
            return
        enc = self._posted_encounter or self._current_encounter
        if not enc or enc.get("status") != "posted":
            messagebox.showinfo("Receipt", "Post charges first to generate a receipt.")
            return
        folder = self.active_patient.get("folder") or ""
        bal = compute_cash_balance(folder)["balance_due"]
        text = build_receipt_text(
            patient_name=self._patient_display_name(),
            posted=enc,
            payment=payment or self._receipt_payment_for_current_visit(),
            account_balance=bal,
            patient_root=folder,
        )
        # One receipt per visit: key by encounter_id (or exam stem fallback) so
        # re-saving overwrites the prior text receipt instead of accumulating.
        unique_key = (enc.get("encounter_id") or "").strip()
        if not unique_key:
            unique_key = Path(enc.get("exam_path") or "").stem or ""
        ReceiptDialog(
            self, text,
            on_save=lambda t: save_receipt_file(
                folder, t, subfolder="cash", unique_key=unique_key,
            ),
        )

    def _show_receipt_folder(self, stream: str = "") -> None:
        """
        Open the Receipt folder dialog. When `stream` is given (cash, package,
        pi, insurance, membership) the dialog is scoped to ONLY that stream's
        receipts and opens that subfolder when the user clicks Open in Explorer.
        Pass stream="" to show everything (legacy unfiltered view).
        """
        if not self.active_patient:
            messagebox.showinfo("Receipt folder", "Select a patient first.")
            return
        folder = self.active_patient.get("folder") or ""
        if not folder:
            messagebox.showinfo("Receipt folder", "No patient folder is available.")
            return
        # Make sure the 5 stream subfolders exist on disk so they show up when
        # the user opens Explorer (even when a stream has no receipts yet).
        try:
            ensure_receipt_subfolders(folder)
        except OSError:
            pass
        ReceiptFolderDialog(
            self, folder,
            patient_name=self._patient_display_name(),
            stream=stream,
        )

    def _post_pi_charges(self) -> None:
        if not self.active_patient or not self._selected_visit:
            return
        folder = self.active_patient.get("folder") or ""
        path = self._selected_visit.get("path") or ""
        try:
            posted = post_encounter_to_pi_case(
                patient_root=folder,
                exam_path=path,
                posted_by=self.current_user,
                patient_id=self.active_patient.get("patient_id") or "",
            )
        except ValueError as e:
            messagebox.showinfo("Cannot post", str(e))
            return
        except Exception as e:
            messagebox.showerror("PI post failed", str(e))
            return
        self._posted_pi_encounter = posted
        self._current_encounter = posted
        self._render_encounter(posted)
        self._refresh_account_balance()
        self._refresh_pi_header()
        self._load_visits()
        messagebox.showinfo(
            "PI case",
            f"Visit posted to PI case at PI/UCR: "
            f"${float(posted.get('amount_charged') or 0):,.2f}",
        )

    def _take_pi_payment(self) -> None:
        if not self.active_patient or not self._posted_pi_encounter:
            messagebox.showinfo("PI payment", "Post this visit to the PI case first.")
            return
        folder = self.active_patient.get("folder") or ""
        path = self._posted_pi_encounter.get("exam_path") or ""
        default_amt = pi_encounter_amount_due(folder, path)
        if default_amt <= 0:
            messagebox.showinfo("PI payment", "No balance due on this visit.")
            return
        PiPaymentDialog(
            self,
            default_amount=default_amt,
            on_save=lambda amt, payer, pdate, memo: self._apply_pi_payment(amt, payer, pdate, memo),
        )

    def _apply_pi_payment(self, amount: float, payer: str, payment_date: str, memo: str) -> None:
        folder = self.active_patient.get("folder") or ""
        posted = self._posted_pi_encounter or {}
        try:
            record_pi_payment(
                patient_root=folder,
                amount=amount,
                payer=payer,
                payment_date=payment_date,
                encounter_id=posted.get("encounter_id") or "",
                exam_path=posted.get("exam_path") or "",
                memo=memo,
                recorded_by=self.current_user,
            )
        except Exception as e:
            messagebox.showerror("PI payment failed", str(e))
            return
        self._refresh_account_balance()
        self._refresh_pi_header()
        self._update_checkout_state(posted)
        messagebox.showinfo("Recorded", f"PI payment ${amount:,.2f} from {payer}.")

    def _pi_adjustment(self) -> None:
        if not self.active_patient:
            return
        PiAdjustmentDialog(
            self,
            on_save=lambda amt, memo: self._apply_pi_adjustment(amt, memo),
        )

    def _apply_pi_adjustment(self, amount: float, memo: str) -> None:
        folder = self.active_patient.get("folder") or ""
        try:
            record_pi_adjustment(
                patient_root=folder,
                amount=amount,
                memo=memo,
                recorded_by=self.current_user,
            )
        except Exception as e:
            messagebox.showerror("Adjustment failed", str(e))
            return
        self._refresh_account_balance()
        self._refresh_pi_header()
        messagebox.showinfo(
            "Adjustment",
            f"Recorded ${amount:,.2f} adjustment.\nNew balance: "
            f"${compute_pi_balance(folder)['balance_due']:,.2f}",
        )

    def _record_settlement(self) -> None:
        if not self.active_patient:
            return
        folder = self.active_patient.get("folder") or ""
        if not folder:
            return
        if is_pi_case_settled(folder):
            messagebox.showinfo("Settlement", "This PI case is already settled.")
            return
        bal = compute_pi_balance(folder)
        if bal["balance_due"] <= 0.01:
            messagebox.showinfo("Settlement", "PI case has no balance due to settle.")
            return
        RecordSettlementDialog(
            self,
            patient_root=folder,
            balance_before=bal["balance_due"],
            on_save=lambda amt, payer, pdate, memo, close: self._apply_settlement(
                amt, payer, pdate, memo, close
            ),
        )

    def _apply_settlement(
        self,
        amount: float,
        payer: str,
        payment_date: str,
        memo: str,
        close_case: bool,
    ) -> None:
        folder = self.active_patient.get("folder") or ""
        try:
            result = record_pi_settlement(
                patient_root=folder,
                settlement_amount=amount,
                payer=payer,
                payment_date=payment_date,
                memo=memo,
                recorded_by=self.current_user,
                close_case=close_case,
            )
        except ValueError as e:
            messagebox.showerror("Settlement failed", str(e))
            return
        except Exception as e:
            messagebox.showerror("Settlement failed", str(e))
            return
        self._refresh_account_balance()
        self._refresh_pi_header()
        enc = self._posted_pi_encounter or self._current_encounter
        if enc:
            self._update_checkout_state(enc)
        self._refresh_receipt_preview()
        folder = self.active_patient.get("folder") or ""
        try:
            save_receipt_file(
                folder,
                build_settlement_receipt_text(
                    patient_name=self._patient_display_name(),
                    patient_root=folder,
                    settlement_amount=amount,
                    write_off=result["write_off"],
                    balance_before=result["balance_before"],
                    payment_date=payment_date,
                    payer=payer,
                    memo=memo,
                ),
                prefix="settlement",
            )
        except Exception:
            pass
        msg = f"Settlement payment: ${amount:,.2f}"
        if result["write_off"] > 0.01:
            msg += f"\nAuto write-off: ${result['write_off']:,.2f}"
        msg += f"\nCase balance: ${result['balance_after']:,.2f}"
        if close_case:
            msg += "\nCase marked Settled."
        messagebox.showinfo("Settlement recorded", msg)

    def _export_pi_case(self) -> None:
        if not self.active_patient:
            return
        folder = self.active_patient.get("folder") or ""
        name = self._patient_display_name()
        ExportCaseDialog(
            self,
            on_export=lambda dfrom, dto: self._run_export(folder, name, dfrom, dto),
        )

    def _open_closeout(self) -> None:
        if not self.active_patient:
            return
        folder = self.active_patient.get("folder") or ""
        name = self._patient_display_name()
        CloseoutDialog(
            self,
            patient_root=folder,
            patient_name=name,
            on_complete=self._refresh_receipt_preview,
        )

    def _run_export(self, folder: str, name: str, date_from: str, date_to: str) -> None:
        try:
            txt_p, csv_p = save_case_exports(
                folder,
                patient_name=name,
                date_from=date_from,
                date_to=date_to,
            )
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            return
        messagebox.showinfo(
            "Case exported",
            f"Summary:\n{txt_p}\n\nLine items CSV:\n{csv_p}",
        )

    def _edit_pi_case(self) -> None:
        if not self.active_patient:
            return
        folder = self.active_patient.get("folder") or ""
        PiCaseEditorDialog(
            self,
            patient_root=folder,
            patient_id=self.active_patient.get("patient_id") or "",
            on_saved=lambda _c: (self._refresh_account_balance(), self._refresh_pi_header()),
        )

    def _open_fee_schedule(self) -> None:
        FeeScheduleDialog(self)

    def open_patient_from_documents(self, patient: dict | None) -> None:
        self.set_active_patient(patient)


class RecordSettlementDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        *,
        patient_root: str,
        balance_before: float,
        on_save,
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.balance_before = balance_before
        self.on_save = on_save
        self.title("Record PI settlement")
        self.geometry("460x380")
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        f = tk.Frame(self, bg=COLOR_CARD, padx=20, pady=20)
        f.pack(fill="both", expand=True)

        tk.Label(
            f,
            text="One lump-sum payment for the whole PI case.\n"
            "Any remaining balance is written off automatically.",
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            font=FONT_SMALL,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        tk.Label(f, text="Balance due", bg=COLOR_CARD).grid(row=1, column=0, sticky="w", pady=4)
        tk.Label(
            f,
            text=f"${balance_before:,.2f}",
            bg=COLOR_CARD,
            font=FONT_BASE_BOLD,
        ).grid(row=1, column=1, sticky="w")

        self.amt_var = tk.StringVar(value=f"{balance_before:.2f}")
        ttk.Label(f, text="Settlement amount").grid(row=2, column=0, sticky="w", pady=4)
        amt_entry = ttk.Entry(f, textvariable=self.amt_var, width=16)
        amt_entry.grid(row=2, column=1, sticky="w")

        self.payer_var = tk.StringVar(value="attorney")
        ttk.Label(f, text="Received from").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(
            f,
            textvariable=self.payer_var,
            values=["attorney", "carrier", "patient", "other"],
            state="readonly",
            width=14,
        ).grid(row=3, column=1, sticky="w")

        from datetime import datetime

        self.date_var = tk.StringVar(value=datetime.now().strftime("%m/%d/%Y"))
        ttk.Label(f, text="Payment date").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.date_var, width=16).grid(row=4, column=1, sticky="w")

        self.memo_var = tk.StringVar()
        ttk.Label(f, text="Memo").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.memo_var, width=28).grid(row=5, column=1, sticky="w")

        self.preview_var = tk.StringVar()
        tk.Label(
            f,
            textvariable=self.preview_var,
            bg="#ECFDF5",
            fg="#065F46",
            font=FONT_BASE,
            padx=8,
            pady=8,
            justify="left",
            wraplength=380,
        ).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 8))

        self.close_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            f,
            text="Mark PI case as Settled",
            variable=self.close_var,
        ).grid(row=7, column=0, columnspan=2, sticky="w")

        btn = tk.Frame(f, bg=COLOR_CARD)
        btn.grid(row=8, column=0, columnspan=2, pady=(12, 0))
        tk.Button(
            btn,
            text="Record settlement",
            command=self._save,
            bg="#047857",
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(btn, text="Cancel", command=self.destroy, relief="flat", cursor="hand2").pack(side="left")

        self.amt_var.trace_add("write", self._update_preview)
        self._update_preview()
        amt_entry.focus_set()
        amt_entry.select_range(0, "end")

    def _parse_amount(self) -> float | None:
        try:
            return float((self.amt_var.get() or "0").replace(",", "").replace("$", ""))
        except ValueError:
            return None

    def _update_preview(self, *_args) -> None:
        amt = self._parse_amount()
        if amt is None:
            self.preview_var.set("Enter a valid settlement amount.")
            return
        if amt <= 0:
            self.preview_var.set("Settlement amount must be greater than zero.")
            return
        prev = preview_pi_settlement(self.patient_root, amt)
        if amt > prev["balance_before"] + 0.01:
            self.preview_var.set(
                f"Amount exceeds balance due (${prev['balance_before']:,.2f})."
            )
            return
        write_off = prev["write_off"]
        if write_off > 0.01:
            self.preview_var.set(
                f"Auto write-off: ${write_off:,.2f}  ·  "
                f"Case balance after: ${prev['balance_after']:,.2f}"
            )
        else:
            self.preview_var.set("Paid in full — case balance after settlement: $0.00")

    def _save(self) -> None:
        amt = self._parse_amount()
        if amt is None or amt <= 0:
            messagebox.showerror("Invalid", "Enter a valid settlement amount.", parent=self)
            return
        prev = preview_pi_settlement(self.patient_root, amt)
        if amt > prev["balance_before"] + 0.01:
            messagebox.showerror(
                "Invalid",
                f"Settlement cannot exceed balance due (${prev['balance_before']:,.2f}).",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Confirm settlement",
            f"Record settlement of ${amt:,.2f}?\n\n"
            f"Write-off: ${prev['write_off']:,.2f}\n"
            f"Case balance after: ${prev['balance_after']:,.2f}"
            + ("\n\nCase will be marked Settled." if self.close_var.get() else ""),
            parent=self,
        ):
            return
        self.on_save(
            amt,
            self.payer_var.get(),
            self.date_var.get(),
            self.memo_var.get(),
            self.close_var.get(),
        )
        self.destroy()


class PiPaymentDialog(tk.Toplevel):
    def __init__(self, parent, *, default_amount: float, on_save):
        super().__init__(parent)
        self.on_save = on_save
        self.title("PI payment")
        self.geometry("400x280")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        f = tk.Frame(self, bg=COLOR_CARD, padx=20, pady=20)
        f.pack(fill="both", expand=True)
        self.amt_var = tk.StringVar(value=f"{default_amount:.2f}")
        ttk.Label(f, text="Amount").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.amt_var, width=14).grid(row=0, column=1, sticky="w")
        self.payer_var = tk.StringVar(value="attorney")
        ttk.Label(f, text="Received from").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(
            f,
            textvariable=self.payer_var,
            values=["attorney", "carrier", "patient", "other"],
            state="readonly",
            width=14,
        ).grid(row=1, column=1, sticky="w")
        from datetime import datetime

        self.date_var = tk.StringVar(value=datetime.now().strftime("%m/%d/%Y"))
        ttk.Label(f, text="Date").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.date_var, width=14).grid(row=2, column=1, sticky="w")
        self.memo_var = tk.StringVar()
        ttk.Label(f, text="Memo").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.memo_var, width=24).grid(row=3, column=1, sticky="w")
        btn = tk.Frame(f)
        btn.grid(row=4, column=0, columnspan=2, pady=(16, 0))
        tk.Button(btn, text="Save", command=self._save, bg="#7C3AED", fg="#fff", relief="flat").pack(
            side="left", padx=4
        )
        tk.Button(btn, text="Cancel", command=self.destroy, relief="flat").pack(side="left")

    def _save(self) -> None:
        try:
            amt = float((self.amt_var.get() or "0").replace(",", "").replace("$", ""))
        except ValueError:
            messagebox.showerror("Invalid", "Enter a valid amount.", parent=self)
            return
        self.on_save(amt, self.payer_var.get(), self.date_var.get(), self.memo_var.get())
        self.destroy()


class PiAdjustmentDialog(tk.Toplevel):
    def __init__(self, parent, *, on_save):
        super().__init__(parent)
        self.on_save = on_save
        self.title("PI adjustment")
        self.geometry("380x200")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        f = tk.Frame(self, padx=20, pady=20)
        f.pack(fill="both", expand=True)
        ttk.Label(
            f,
            text="Negative = reduction/write-off · Positive increases balance",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.amt_var = tk.StringVar(value="-0.00")
        ttk.Label(f, text="Amount").grid(row=1, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.amt_var, width=14).grid(row=1, column=1, sticky="w")
        self.memo_var = tk.StringVar()
        ttk.Label(f, text="Memo").grid(row=2, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.memo_var, width=28).grid(row=2, column=1, sticky="w")
        btn = tk.Frame(f)
        btn.grid(row=3, column=0, columnspan=2, pady=(14, 0))
        tk.Button(btn, text="Save", command=self._save).pack(side="left", padx=4)
        tk.Button(btn, text="Cancel", command=self.destroy).pack(side="left")

    def _save(self) -> None:
        try:
            amt = float((self.amt_var.get() or "0").replace(",", ""))
        except ValueError:
            messagebox.showerror("Invalid", "Enter a valid amount.", parent=self)
            return
        self.on_save(amt, self.memo_var.get())
        self.destroy()


class ExportCaseDialog(tk.Toplevel):
    def __init__(self, parent, *, on_export):
        super().__init__(parent)
        self.on_export = on_export
        self.title("Export PI case")
        self.geometry("360x160")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        f = tk.Frame(self, padx=20, pady=20)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="From DOS (optional)").grid(row=0, column=0, sticky="w")
        self.from_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.from_var, width=12).grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="To DOS (optional)").grid(row=1, column=0, sticky="w", pady=8)
        self.to_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.to_var, width=12).grid(row=1, column=1, sticky="w")
        btn = tk.Frame(f)
        btn.grid(row=2, column=0, columnspan=2, pady=(14, 0))
        tk.Button(btn, text="Export TXT + CSV", command=self._go).pack(side="left", padx=4)
        tk.Button(btn, text="Cancel", command=self.destroy).pack(side="left")

    def _go(self) -> None:
        self.on_export(self.from_var.get().strip(), self.to_var.get().strip())
        self.destroy()


class PaymentDialog(tk.Toplevel):
    def __init__(
        self,
        parent: BillingPage,
        *,
        default_amount: float,
        on_save,
    ):
        super().__init__(parent)
        self.on_save = on_save
        self.title("Take payment")
        self.geometry("360x220")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.configure(bg=COLOR_BG_APP)

        f = tk.Frame(self, bg=COLOR_CARD, padx=20, pady=20)
        f.pack(fill="both", expand=True)

        tk.Label(f, text="Amount", bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE).grid(
            row=0, column=0, sticky="w", pady=4
        )
        self.amt_var = tk.StringVar(value=f"{default_amount:.2f}")
        ttk.Entry(f, textvariable=self.amt_var, width=14).grid(row=0, column=1, sticky="w", pady=4)

        tk.Label(f, text="Method", bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE).grid(
            row=1, column=0, sticky="w", pady=4
        )
        self.method_var = tk.StringVar(value="card")
        ttk.Combobox(
            f,
            textvariable=self.method_var,
            values=["cash", "card", "check", "other"],
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="w", pady=4)

        tk.Label(f, text="Payment date", bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE).grid(
            row=2, column=0, sticky="w", pady=4
        )
        from datetime import datetime

        self.date_var = tk.StringVar(value=datetime.now().strftime("%m/%d/%Y"))
        ttk.Entry(f, textvariable=self.date_var, width=14).grid(row=2, column=1, sticky="w", pady=4)

        btn = tk.Frame(f, bg=COLOR_CARD)
        btn.grid(row=3, column=0, columnspan=2, pady=(16, 0))
        tk.Button(
            btn,
            text="Record payment",
            command=self._save,
            bg=COLOR_GREEN,
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=12,
            cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            btn,
            text="Cancel",
            command=self.destroy,
            relief="flat",
            font=FONT_BASE,
            cursor="hand2",
        ).pack(side="left")

    def _save(self) -> None:
        try:
            amt = float((self.amt_var.get() or "0").replace(",", "").replace("$", ""))
        except ValueError:
            messagebox.showerror("Invalid", "Enter a valid amount.", parent=self)
            return
        self.on_save(amt, self.method_var.get(), self.date_var.get())
        self.destroy()


class ReceiptFolderDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        patient_root: str,
        *,
        patient_name: str = "",
        stream: str = "",
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.patient_name = patient_name
        self.stream = (stream or "").strip().lower()
        self._docs: list[BillingDocument] = []
        # Tailor the title + description to the active stream so the user is
        # certain they're looking at only that money stream's receipts.
        stream_label = STREAM_DISPLAY_LABELS.get(self.stream, "")
        title_prefix = f"{stream_label} receipts" if stream_label else "Billing documents"
        title = f"{title_prefix} — {patient_name}" if patient_name else title_prefix
        self.title(title)
        self.geometry("720x520")
        self.minsize(560, 420)
        self.transient(parent.winfo_toplevel())

        bar = tk.Frame(self, bg=COLOR_BG_APP)
        bar.pack(fill="x", padx=8, pady=8)
        desc_map = {
            "cash": "Cash receipts (text + PDF) — one per posted cash visit.",
            "package": "Package contracts and statements — kept separate from cash math.",
            "pi": "PI case summaries, settlement receipts, and attorney packet copies.",
            "insurance": "Insurance EOBs and remittance receipts (reserved for future).",
            "membership": "Membership receipts and renewal statements (reserved for future).",
        }
        desc = desc_map.get(
            self.stream,
            "Cash receipts, PI settlements, case summaries, and attorney packet copies.",
        )
        tk.Label(
            bar,
            text=desc,
            bg=COLOR_BG_APP,
            fg=COLOR_MUTED,
            font=FONT_SMALL,
            wraplength=480,
            justify="left",
        ).pack(side="left")
        tk.Button(
            bar,
            text="Open folder in Explorer",
            command=self._open_folder,
            bg=COLOR_CARD,
            fg=COLOR_ACCENT,
            relief="flat",
            font=FONT_BASE_BOLD,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            padx=10,
            pady=4,
            cursor="hand2",
        ).pack(side="right")

        body = tk.Frame(self, bg=COLOR_BG_APP)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)

        left = tk.Frame(body, bg=COLOR_BG_APP)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        tk.Label(left, text="Documents", bg=COLOR_BG_APP, fg=COLOR_TEXT, font=FONT_BASE_BOLD).pack(
            anchor="w", pady=(0, 4)
        )
        list_wrap = tk.Frame(left, bg=COLOR_BORDER)
        list_wrap.pack(fill="y")
        self.listbox = tk.Listbox(
            list_wrap,
            width=28,
            height=18,
            font=FONT_BASE,
            activestyle="none",
            selectbackground=COLOR_VISIT_ROW_SELECTED,
            selectforeground=COLOR_TEXT,
            highlightthickness=0,
            borderwidth=0,
        )
        lb_scroll = ttk.Scrollbar(list_wrap, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=lb_scroll.set)
        self.listbox.pack(side="left", fill="y")
        lb_scroll.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Double-Button-1>", lambda _e: self._open_selected())

        preview_wrap = tk.Frame(body, bg=COLOR_BORDER)
        preview_wrap.grid(row=0, column=1, sticky="nsew")
        preview_wrap.rowconfigure(0, weight=1)
        preview_wrap.columnconfigure(0, weight=1)
        self.preview = tk.Text(
            preview_wrap,
            wrap="word",
            font=("Consolas", 10),
            bg=COLOR_CARD,
            fg=COLOR_TEXT,
            relief="flat",
            padx=8,
            pady=8,
        )
        prev_scroll = ttk.Scrollbar(preview_wrap, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=prev_scroll.set, state="disabled")
        self.preview.grid(row=0, column=0, sticky="nsew")
        prev_scroll.grid(row=0, column=1, sticky="ns")

        actions = tk.Frame(self, bg=COLOR_BG_APP)
        actions.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(
            actions,
            text="Open selected",
            command=self._open_selected,
            bg=COLOR_ACCENT,
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=12,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(actions, text="Close", command=self.destroy, relief="flat", cursor="hand2").pack(side="right")

        self._reload_list()

    def _reload_list(self) -> None:
        self.listbox.delete(0, "end")
        streams = (self.stream,) if self.stream else None
        self._docs = list_billing_documents(self.patient_root, streams=streams)
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.configure(state="disabled")
        if not self._docs:
            empty_msg = (
                f"(No {STREAM_DISPLAY_LABELS.get(self.stream, '').lower()} receipts yet)"
                if self.stream
                else "(No billing documents yet)"
            )
            self.listbox.insert("end", empty_msg)
            self.preview.configure(state="normal")
            self.preview.insert(
                "1.0",
                "No saved billing documents yet.\n\n"
                "• Cash: Post cash → Receipt → Save to patient folder\n"
                "• PI: Record settlement or Attorney packet → Build packet folder",
            )
            self.preview.configure(state="disabled")
            return
        for doc in self._docs:
            self.listbox.insert("end", doc.label)
        self.listbox.selection_set(0)
        self._load_preview(0)

    def _on_select(self, _event=None) -> None:
        sel = self.listbox.curselection()
        if not sel or not self._docs:
            return
        self._load_preview(sel[0])

    def _load_preview(self, index: int) -> None:
        if index < 0 or index >= len(self._docs):
            return
        doc = self._docs[index]
        path = doc.path
        # Preferred preview source: a .txt sidecar attached to the document
        # (cash receipts carry one so the row can show the receipt text inline
        # even though the canonical file is a .pdf).
        text = ""
        if doc.text_sidecar is not None and doc.text_sidecar.is_file():
            try:
                text = doc.text_sidecar.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = ""
            except OSError as e:
                text = f"Could not read receipt text:\n{e}"
        if not text:
            if path.suffix.lower() == ".pdf":
                # PDF without a text sidecar — show a friendly placeholder so the
                # user double-clicks (or hits Open) to view it in their PDF viewer.
                if path.exists():
                    text = (
                        "(PDF document — preview not available in this pane.)\n\n"
                        "Double-click the row, or click  Open selected,  to open\n"
                        "the PDF in your default viewer."
                    )
                else:
                    text = (
                        "(PDF not generated yet.)\n\n"
                        "Double-click the row, or click  Open selected,  to\n"
                        "generate the PDF and open it in your default viewer.\n"
                        "It will be saved into the Cash receipts folder."
                    )
            else:
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    text = (
                        "(Binary or non-UTF-8 document — preview not available.)\n\n"
                        "Click  Open  to view it in its default application."
                    )
                except OSError as e:
                    text = f"Could not read document:\n{e}"
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", f"{doc.label}\n{'=' * 42}\n\n{text}")
        self.preview.configure(state="disabled")

    def _selected_doc(self) -> "BillingDocument | None":
        if not self._docs:
            return None
        sel = self.listbox.curselection()
        if not sel:
            return None
        idx = sel[0]
        if idx < 0 or idx >= len(self._docs):
            return None
        return self._docs[idx]

    def _selected_path(self) -> Path | None:
        doc = self._selected_doc()
        return doc.path if doc else None

    def _open_selected(self) -> None:
        doc = self._selected_doc()
        if not doc:
            messagebox.showinfo("Receipt folder", "Select a receipt from the list.", parent=self)
            return
        path = doc.path
        # Cash entries lazy-generate their PDF on first open: the .txt sidecar
        # is the source of truth and the .pdf is "printed" only when needed.
        if path.suffix.lower() == ".pdf" and not path.exists():
            # Lazy-generate on first open. Cash and Package each have their own
            # generator that knows how to rebuild the PDF from authoritative
            # storage (encounter sidecar / package event log).
            try:
                if doc.stream == "cash":
                    from billing_pdf import ensure_cash_receipt_pdf
                    path = ensure_cash_receipt_pdf(
                        self.patient_root,
                        path,
                        patient_name=self.patient_name or "",
                        text_sidecar=doc.text_sidecar,
                    )
                elif doc.stream == "package":
                    from package_pdf import ensure_package_pdf
                    path = ensure_package_pdf(
                        self.patient_root,
                        path,
                        patient_name=self.patient_name or "",
                    )
            except Exception as e:
                messagebox.showerror(
                    "Open receipt",
                    f"Could not generate PDF:\n\n{e}",
                    parent=self,
                )
                return
        try:
            os.startfile(str(path.resolve()))  # type: ignore[attr-defined]
        except OSError as e:
            messagebox.showerror("Open receipt", f"Could not open file:\n{path}\n\n{e}", parent=self)

    def _open_folder(self) -> None:
        try:
            # When the dialog is scoped to a stream, jump the user straight to
            # that subfolder so they land in the right place in Explorer.
            open_receipts_folder(self.patient_root, subfolder=self.stream or "")
        except OSError as e:
            messagebox.showerror("Receipt folder", f"Could not open folder:\n\n{e}", parent=self)


class ReceiptDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, text: str, on_save):
        super().__init__(parent)
        self.on_save = on_save
        self.title("Receipt")
        self.geometry("480x520")
        self.transient(parent.winfo_toplevel())

        bar = tk.Frame(self, bg=COLOR_BG_APP)
        bar.pack(fill="x", padx=8, pady=8)
        tk.Button(
            bar,
            text="Save to patient folder",
            command=self._save_file,
            bg=COLOR_ACCENT,
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(bar, text="Close", command=self.destroy, relief="flat", cursor="hand2").pack(side="left")

        self.txt = tk.Text(self, wrap="word", font=("Consolas", 10))
        self.txt.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.txt.insert("1.0", text)

    def _save_file(self) -> None:
        path = self.on_save(self.txt.get("1.0", "end-1c"))
        messagebox.showinfo("Saved", f"Receipt saved:\n{path}", parent=self)
