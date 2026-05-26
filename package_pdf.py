# package_pdf.py — State-compliant prepaid treatment plan contract + statement PDFs.
#
# Two public entry points:
#   build_contract_pdf(patient_root, patient_name, package_id, ...)  -> Path
#   build_statement_pdf(patient_root, patient_name, package_id, ...) -> Path
#
# Both wrap-and-write to <patient>/billing/receipts/ to be visible in the
# Receipt folder dialog alongside cash and PI receipts.
#
# Contract field map (NC superset — covers ND and most other states):
#   1.  plan_name
#   2.  plan_duration_visits + plan_duration_days
#   3.  therapeutic_objectives (free text; supplied at sale time)
#   4.  purchase_price
#   5.  included_services_table (CPT + description + visit count + retail value)
#   6.  excluded_services_disclaimer (bold)
#   7.  cancellation_policy_text
#   8.  no_show_policy_text
#   9.  termination_refund_clause
#   10. prorated_value_per_visit
#   11. signature_block (patient + clinic representative)
#   12. clinic_block (name/address/phone)
#   13. purchase_date + expiration_date

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas as pdf_canvas

    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

from config import CLINIC_ADDR, CLINIC_NAME, CLINIC_PHONE_FAX
from billing_pdf import (
    _draw_header_band,
    _draw_section_header,
    _draw_title_block,
    _new_pdf_canvas,
    _new_receipt_path,
    _require_reportlab,
)
from billing_storage import patient_billing_root
from package_engine import compute_package_state, status_label
from package_storage import (
    all_events_for_package,
    find_purchase_event,
    load_package_log,
)


# ---------------------------------------------------------------------------
# Canonical text renderers — single source of truth for both .txt sidecars
# (shown inline in the Receipt folder dialog) and the underlying PDF layout.
# Keeping these in one place guarantees the .txt and .pdf never drift apart.
# ---------------------------------------------------------------------------

def build_package_statement_text(
    patient_root: str | Path,
    *,
    patient_name: str,
    package_id: str,
    statement_date: str = "",
) -> str:
    """
    Plain-text Statement of Account for a single package. Mirrors the
    PackageDetailDialog detail view (same field set / event log) so the
    Receipt folder preview pane shows exactly what the user already saw
    in View detail.
    """
    events = all_events_for_package(patient_root, package_id)
    state = compute_package_state(events)
    purchase = state.get("purchase") or {}
    issued = statement_date or datetime.now().strftime("%m/%d/%Y %I:%M %p")

    sep = "=" * 56
    sub = "-" * 56
    lines: list[str] = []
    lines.append("STATEMENT OF ACCOUNT — PREPAID PLAN")
    lines.append(sep)
    lines.append(f"Patient:              {patient_name}")
    lines.append(f"Issued:               {issued}")
    lines.append("")

    lines.append(f"{(purchase.get('name') or 'Package').upper()} "
                 f"({status_label(state.get('status') or '')})")
    lines.append(sub)
    lines.append(f"Package ID:           {package_id}")
    lines.append(f"Catalog template:     {purchase.get('catalog_id') or '(ad-hoc)'}")
    lines.append(f"Plan name:            {purchase.get('name') or ''}")
    lines.append(f"Purchase date:        {purchase.get('purchase_date') or ''}")
    lines.append(f"Expiration:           {purchase.get('expiration_date') or '(none)'}")
    lines.append(f"Total visits:         {purchase.get('total_visits') or 0}")
    lines.append(f"CPT whitelist:        {', '.join(purchase.get('cpt_whitelist') or [])}")
    lines.append(f"Purchase price:       ${float(purchase.get('purchase_price') or 0):,.2f}")
    lines.append(f"Pro-rata per visit:   ${float(purchase.get('prorated_value_per_visit') or 0):,.2f}")

    # ---- PAYMENT STATUS — surfaced prominently so the patient and clinic
    # both see at a glance whether the package is paid in full or has a
    # remaining balance. Same wording / structure as the document preview
    # pane so the user gets a consistent story across all views.
    lines.append("")
    lines.append("PAYMENT STATUS")
    lines.append(sub)
    purchase_price = float(purchase.get("purchase_price") or 0)
    amount_paid = float(state.get("amount_paid") or 0)
    balance_due = float(state.get("purchase_balance_due") or 0)
    lines.append(f"Purchase price:       ${purchase_price:,.2f}")
    lines.append(f"Amount paid (so far): ${amount_paid:,.2f}")
    if state.get("is_paid_in_full"):
        lines.append("Balance:              PAID IN FULL")
    else:
        lines.append(f"Balance:              ${balance_due:,.2f}  (REMAINING TO PAY)")

    lines.append("")
    lines.append("VISITS & DEFERRED REVENUE")
    lines.append(sub)
    lines.append(f"Visits used:          {state.get('visits_used') or 0}")
    lines.append(f"Visits remaining:     {state.get('visits_remaining') or 0}")
    lines.append(f"Revenue recognized:   ${float(state.get('value_recognized') or 0):,.2f}")
    lines.append(f"Refunds paid:         ${float(state.get('refund_paid') or 0):,.2f}")
    lines.append(f"Deferred remaining:   ${float(state.get('deferred_revenue_remaining') or 0):,.2f}")

    objectives = (purchase.get("therapeutic_objectives") or "").strip()
    if objectives:
        lines.append("")
        lines.append("THERAPEUTIC OBJECTIVES")
        lines.append(sub)
        for chunk in objectives.splitlines() or [objectives]:
            lines.append(chunk)

    if purchase.get("memo"):
        lines.append("")
        lines.append(f"Memo: {purchase.get('memo')}")

    lines.append("")
    lines.append(sep)
    lines.append("EVENT LOG (append-only — source of truth)")
    lines.append(sep)
    for e in events:
        ts = (e.get("timestamp") or "").replace("T", " ")
        etype = (e.get("type") or "").upper()
        extra = ""
        if e.get("type") == "redemption":
            cpts_list = e.get("cpts_redeemed") or []
            if cpts_list:
                cpt_label = "CPTs " + ", ".join(str(c) for c in cpts_list)
            else:
                cpt_label = f"CPT {e.get('cpt_redeemed') or ''}"
            extra = (
                f" · {cpt_label}"
                f" · ${float(e.get('value_recognized') or 0):,.2f}"
                f" · DOS {e.get('date_of_service') or ''}"
            )
        elif e.get("type") == "refund":
            extra = (
                f" · ${float(e.get('amount') or 0):,.2f}"
                f" · {e.get('method') or ''}"
                f" · strategy: {e.get('refund_strategy') or ''}"
            )
        elif e.get("type") == "cancellation":
            extra = f" · {(e.get('reason') or '')[:60]}"
        elif e.get("type") == "payment":
            extra = (
                f" · ${float(e.get('amount') or 0):,.2f}"
                f" · {e.get('method') or ''}"
                f" · {e.get('payment_date') or ''}"
            )
            if e.get("memo"):
                extra += f" · {(e.get('memo') or '')[:40]}"
        lines.append(f"  {ts}  {etype}{extra}")

    return "\n".join(lines)


def build_package_contract_text(
    patient_root: str | Path,
    *,
    patient_name: str,
    package_id: str,
    therapeutic_objectives: str = "",
    excluded_disclaimer: str = "",
    cancellation_policy: str = "",
    no_show_policy: str = "",
    termination_clause: str = "",
) -> str:
    """
    Plain-text Prepaid Treatment Plan Contract for the Receipt folder preview
    pane. The PDF carries the same fields with signature lines and formatted
    layout; the text version omits the visual signature block but keeps every
    legal section so the user can read the agreement inline.
    """
    purchase = find_purchase_event(patient_root, package_id) or {}
    sep = "=" * 56
    sub = "-" * 56
    lines: list[str] = []
    lines.append("PREPAID TREATMENT PLAN — CONTRACT")
    lines.append(sep)
    lines.append(f"Patient:               {patient_name}")
    lines.append(f"Package ID:            {package_id}")
    lines.append(f"Plan name:             {purchase.get('name') or ''}")
    lines.append(f"Plan duration:         {purchase.get('total_visits') or 0} visit(s)"
                 + (f"  /  {purchase.get('expiration_months') or ''} months"
                    if purchase.get('expiration_months') else ""))
    lines.append(f"Purchase date:         {purchase.get('purchase_date') or ''}")
    lines.append(f"Expiration date:       {purchase.get('expiration_date') or '(none)'}")
    lines.append(f"Purchase price:        ${float(purchase.get('purchase_price') or 0):,.2f}")
    lines.append(f"Pro-rata value/visit:  ${float(purchase.get('prorated_value_per_visit') or 0):,.2f}")

    obj = (therapeutic_objectives or purchase.get("therapeutic_objectives") or "").strip()
    if obj:
        lines.append("")
        lines.append("THERAPEUTIC OBJECTIVES")
        lines.append(sub)
        for chunk in obj.splitlines() or [obj]:
            lines.append(chunk)

    lines.append("")
    lines.append("INCLUDED SERVICES")
    lines.append(sub)
    for cpt in purchase.get("cpt_whitelist") or []:
        lines.append(f"  · CPT {cpt}    Service covered under this plan (per visit)")

    lines.append("")
    lines.append("EXCLUDED SERVICES — IMPORTANT")
    lines.append(sub)
    lines.append(excluded_disclaimer
                 or purchase.get("excluded_services_disclaimer")
                 or DEFAULT_EXCLUDED_DISCLAIMER)

    lines.append("")
    lines.append("CANCELLATION POLICY")
    lines.append(sub)
    lines.append(cancellation_policy
                 or purchase.get("cancellation_policy")
                 or DEFAULT_CANCELLATION_POLICY)

    lines.append("")
    lines.append("MISSED APPOINTMENT POLICY")
    lines.append(sub)
    lines.append(no_show_policy
                 or purchase.get("no_show_policy")
                 or DEFAULT_NO_SHOW_POLICY)

    lines.append("")
    lines.append("RIGHT TO TERMINATE · REFUND CALCULATION")
    lines.append(sub)
    lines.append(termination_clause or DEFAULT_TERMINATION_CLAUSE)

    lines.append("")
    lines.append(sep)
    lines.append("SIGNATURES")
    lines.append(sep)
    lines.append("Patient signature:  ________________________   Date: __________")
    lines.append("")
    lines.append("Clinic rep:         ________________________   Date: __________")
    lines.append("")
    lines.append(f"{(CLINIC_NAME or '').strip()}  ·  {(CLINIC_ADDR or '').strip()}  ·  "
                 f"{(CLINIC_PHONE_FAX or '').strip()}")
    return "\n".join(lines)


COLOR_PRIMARY = "#1E3A8A"
COLOR_TEXT_DARK = "#0F172A"
COLOR_TEXT_MUTED = "#475569"
COLOR_BORDER = "#CBD5E1"
COLOR_BG_BAND = "#F1F5F9"
COLOR_BG_HIGHLIGHT = "#FEF3C7"


# ---------------------------------------------------------------------------
# Default boilerplate text — overridable per template via the catalog editor
# ---------------------------------------------------------------------------

DEFAULT_EXCLUDED_DISCLAIMER = (
    "IMPORTANT: This plan covers ONLY the services listed under \"Included Services\" "
    "below. Any service or product not listed — including but not limited to extra "
    "therapy modalities, imaging, durable medical equipment, nutritional supplements, "
    "or evaluation and management visits — IS NOT included in the prepaid price and "
    "will be billed separately at the clinic's standard fee schedule."
)

DEFAULT_CANCELLATION_POLICY = (
    "Cancellations made at least 24 hours in advance are not charged. Same-day "
    "cancellations or missed appointments may forfeit one (1) visit from this plan "
    "at the clinic's discretion."
)

DEFAULT_NO_SHOW_POLICY = (
    "A no-call/no-show appointment will be deducted as one (1) used visit from the "
    "plan, consistent with the cancellation policy above."
)

DEFAULT_TERMINATION_CLAUSE = (
    "The patient may terminate this plan at any time prior to its expiration by "
    "delivering written notice (signed and dated) to the clinic. The clinic will "
    "issue the appropriate pro-rata refund within ten (10) business days of receiving "
    "the termination notice. No administrative fees apply (only true pass-through "
    "fees, such as credit card processing, may be withheld). Refund calculation: "
    "the purchase price multiplied by (visits remaining / total visits)."
)


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------

def _draw_wrapped_text(
    c: "pdf_canvas.Canvas",
    text: str,
    *,
    x: float,
    y: float,
    max_width: float,
    font_name: str = "Helvetica",
    font_size: int = 10,
    leading: float = 14,
    color_hex: str = COLOR_TEXT_DARK,
    page_break: Callable[[], float] | None = None,
    min_y: float = 0.0,
) -> float:
    """
    Draw word-wrapped text. Returns the y coord BELOW the final line.

    Page-break support: if `page_break` is provided, a line about to be
    drawn below `min_y` triggers `page_break()` (which is expected to
    showPage + redraw any page chrome and return the new top-of-content y).
    Without these args, behavior is identical to the original — used by
    callers that draw inside fixed-height callout boxes where wrapping is
    bounded.
    """
    if not text:
        return y
    c.setFont(font_name, font_size)
    c.setFillColor(colors.HexColor(color_hex))

    def _maybe_break(current_y: float) -> float:
        if page_break is not None and current_y < min_y:
            new_y = page_break()
            # After a page break the canvas state is reset — re-assert
            # font + fill so the next line keeps the same look.
            c.setFont(font_name, font_size)
            c.setFillColor(colors.HexColor(color_hex))
            return new_y
        return current_y

    words = text.split()
    line = ""
    for word in words:
        trial = (line + " " + word).strip()
        width = c.stringWidth(trial, font_name, font_size)
        if width <= max_width:
            line = trial
            continue
        y = _maybe_break(y)
        c.drawString(x, y, line)
        y -= leading
        line = word
    if line:
        y = _maybe_break(y)
        c.drawString(x, y, line)
        y -= leading
    return y


def _draw_kv_row(
    c: "pdf_canvas.Canvas",
    *,
    x: float,
    y: float,
    label: str,
    value: str,
    label_width: float = 130,
) -> float:
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
    c.drawString(x, y, label)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
    c.drawString(x + label_width, y, value or "—")
    return y - 16


def _draw_included_services_table(
    c: "pdf_canvas.Canvas",
    *,
    margin: float,
    inner_w: float,
    y_top: float,
    rows: list[tuple[str, str, str, str]],  # (cpt, description, count, value)
    page_break: Callable[[], float] | None = None,
    min_y: float = 0.0,
) -> float:
    if not rows:
        return y_top
    header_h = 18
    row_h = 16

    col_xs = [margin + 8, margin + 80, margin + inner_w - 180, margin + inner_w - 90]
    headers = ["CPT", "Description", "Count", "Retail value"]

    def _draw_header(y_h: float) -> float:
        c.setFillColor(colors.HexColor(COLOR_BG_BAND))
        c.rect(margin, y_h - header_h, inner_w, header_h, stroke=0, fill=1)
        c.setFillColor(colors.HexColor(COLOR_PRIMARY))
        c.setFont("Helvetica-Bold", 9)
        for label, xc in zip(headers, col_xs):
            c.drawString(xc, y_h - header_h + 5, label.upper())
        return y_h - header_h

    y = _draw_header(y_top)
    c.setStrokeColor(colors.HexColor(COLOR_BORDER))
    c.setLineWidth(0.4)
    for cpt, desc, count, value in rows:
        # If the next row would land below the bottom margin, page-break and
        # re-draw the column header on the new page so the table remains
        # readable across pages (no widow rows under a missing header).
        if page_break is not None and y - row_h < min_y:
            y_new = page_break()
            y = _draw_header(y_new)
            c.setStrokeColor(colors.HexColor(COLOR_BORDER))
            c.setLineWidth(0.4)
        y -= row_h
        c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
        c.setFont("Helvetica", 10)
        c.drawString(col_xs[0], y + 4, cpt or "")
        c.drawString(col_xs[1], y + 4, (desc or "")[:48])
        c.setFont("Helvetica", 10)
        c.drawString(col_xs[2], y + 4, count or "")
        c.drawString(col_xs[3], y + 4, value or "")
        c.line(margin, y, margin + inner_w, y)
    return y - 6


def _draw_signature_block(
    c: "pdf_canvas.Canvas",
    *,
    margin: float,
    inner_w: float,
    y_top: float,
) -> float:
    y = y_top
    line_w = (inner_w - 30) / 2
    c.setStrokeColor(colors.HexColor(COLOR_TEXT_DARK))
    c.setLineWidth(0.8)
    # Patient
    c.line(margin, y, margin + line_w, y)
    c.line(margin + line_w + 30, y, margin + inner_w, y)
    y_label = y - 12
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
    c.drawString(margin, y_label, "Patient signature")
    c.drawString(margin + line_w + 30, y_label, "Date")
    y -= 36
    # Clinic
    c.line(margin, y, margin + line_w, y)
    c.line(margin + line_w + 30, y, margin + inner_w, y)
    y_label = y - 12
    c.drawString(margin, y_label, "Clinic representative")
    c.drawString(margin + line_w + 30, y_label, "Date")
    return y - 24


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def build_contract_pdf(
    patient_root: str | Path,
    *,
    patient_name: str,
    package_id: str,
    therapeutic_objectives: str = "",
    included_services_rows: list[tuple[str, str, str, str]] | None = None,
    excluded_disclaimer: str = "",
    cancellation_policy: str = "",
    no_show_policy: str = "",
    termination_clause: str = "",
) -> Path:
    """
    Generate a state-compliant prepaid treatment plan contract PDF for the
    given package and write it to <patient>/billing/receipts/.

    The included_services_rows are typically [(cpt, label, "Up to 10", "$75.00"), ...]
    where label/count/value come from the catalog template snapshot stored in
    the purchase event.
    """
    _require_reportlab()
    purchase = find_purchase_event(patient_root, package_id)
    if not purchase:
        raise ValueError(f"Package {package_id} has no purchase event.")

    # One contract per package_id — overwrites previous if re-printed (a contract
    # is the canonical signed agreement; multiple copies clutter the folder).
    out = _new_receipt_path(
        patient_root,
        prefix="package_contract",
        subfolder="package",
        unique_key=package_id,
    )
    # Always write a .txt sidecar alongside so the Receipt folder dialog can
    # preview the contract inline without opening the PDF viewer.
    try:
        sidecar = out.with_suffix(".txt")
        sidecar.write_text(
            build_package_contract_text(
                patient_root,
                patient_name=patient_name,
                package_id=package_id,
                therapeutic_objectives=therapeutic_objectives,
                excluded_disclaimer=excluded_disclaimer,
                cancellation_policy=cancellation_policy,
                no_show_policy=no_show_policy,
                termination_clause=termination_clause,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass  # PDF must still succeed even if sidecar fails.

    c = _new_pdf_canvas(out, pagesize=LETTER)
    page_w, page_h = LETTER
    margin = 0.55 * inch
    inner_w = page_w - 2 * margin

    # Minimum y any content may be drawn at — leaves room for the bottom-right
    # "Page N of M" stamp drawn by NumberedCanvas and a small visual breath.
    min_y = margin + 18

    def _page_break() -> float:
        """showPage + redraw the clinic header band on the new page.

        Returns the fresh top-of-content y just below the band. The
        contract title block is intentionally NOT redrawn — that belongs
        only to page 1; continuation pages just show the header band.
        """
        c.showPage()
        return _draw_header_band(c, page_w, page_h)

    def _ensure_room(current_y: float, *, needed: float) -> float:
        """Force a page break if `needed` height won't fit above min_y."""
        if current_y - needed < min_y:
            return _page_break()
        return current_y

    y = _draw_header_band(c, page_w, page_h)
    y = _draw_title_block(
        c,
        page_w,
        y,
        title="Prepaid Treatment Plan Contract",
        subtitle="Signed agreement — please retain a copy for your records",
        receipt_no=package_id,
    )

    # --- Patient + plan summary (banner + ~7 kv rows ≈ 140 high) ---
    y = _ensure_room(y - 6, needed=160)
    c.setFillColor(colors.HexColor(COLOR_BG_BAND))
    c.rect(margin, y - 18, inner_w, 18, stroke=0, fill=1)
    c.setFillColor(colors.HexColor(COLOR_PRIMARY))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin + 8, y - 13, "PLAN SUMMARY")
    y -= 26

    y = _draw_kv_row(c, x=margin, y=y, label="Patient", value=patient_name)
    y = _draw_kv_row(c, x=margin, y=y, label="Plan name", value=purchase.get("name") or "")
    y = _draw_kv_row(
        c, x=margin, y=y,
        label="Plan duration",
        value=f"{purchase.get('total_visits') or 0} visit(s)"
              + (f" or {purchase.get('expiration_months') or ''} months" if purchase.get('expiration_months') else ""),
    )
    y = _draw_kv_row(c, x=margin, y=y, label="Purchase date", value=purchase.get("purchase_date") or "")
    y = _draw_kv_row(c, x=margin, y=y, label="Expiration date", value=purchase.get("expiration_date") or "(none)")
    y = _draw_kv_row(
        c, x=margin, y=y,
        label="Purchase price",
        value=f"${float(purchase.get('purchase_price') or 0):,.2f}",
    )
    y = _draw_kv_row(
        c, x=margin, y=y,
        label="Pro-rata value/visit",
        value=f"${float(purchase.get('prorated_value_per_visit') or 0):,.2f}",
    )

    # --- Therapeutic objectives ---
    if therapeutic_objectives or purchase.get("therapeutic_objectives"):
        y = _ensure_room(y - 6, needed=80)
        y = _draw_section_header(c, page_w, y, "Therapeutic objectives")
        y = _draw_wrapped_text(
            c,
            therapeutic_objectives or purchase.get("therapeutic_objectives") or "",
            x=margin, y=y, max_width=inner_w,
            page_break=_page_break, min_y=min_y,
        )

    # --- Included services ---
    rows = list(included_services_rows or [])
    if not rows:
        for cpt in purchase.get("cpt_whitelist") or []:
            rows.append((str(cpt), "Service covered under this plan", "Per visit", ""))
    # header (~36) + table header (~18) + room for at least 2 rows (~32)
    y = _ensure_room(y - 6, needed=120)
    y = _draw_section_header(c, page_w, y, "Included services")
    y = _draw_included_services_table(
        c, margin=margin, inner_w=inner_w, y_top=y - 6, rows=rows,
        page_break=_page_break, min_y=min_y,
    )

    # --- Excluded services disclaimer (BOLD callout) ---
    # Section header (~36) + callout box (60) + bottom gap (6) ≈ 102 high.
    y = _ensure_room(y - 4, needed=110)
    y = _draw_section_header(c, page_w, y, "Excluded services — important")
    text = (excluded_disclaimer or purchase.get("excluded_services_disclaimer") or DEFAULT_EXCLUDED_DISCLAIMER)
    c.setFillColor(colors.HexColor(COLOR_BG_HIGHLIGHT))
    box_top = y
    box_h = 60
    c.rect(margin, y - box_h, inner_w, box_h, stroke=0, fill=1)
    y_text = y - 12
    _draw_wrapped_text(
        c, text,
        x=margin + 8, y=y_text, max_width=inner_w - 16,
        font_name="Helvetica-Bold", font_size=10, leading=12,
    )
    y = box_top - box_h - 6

    # --- Cancellation + no-show policies ---
    if (cancellation_policy or purchase.get("cancellation_policy") or DEFAULT_CANCELLATION_POLICY):
        y = _ensure_room(y, needed=80)
        y = _draw_section_header(c, page_w, y, "Cancellation policy")
        y = _draw_wrapped_text(
            c,
            cancellation_policy or purchase.get("cancellation_policy") or DEFAULT_CANCELLATION_POLICY,
            x=margin, y=y, max_width=inner_w,
            page_break=_page_break, min_y=min_y,
        )
    if (no_show_policy or purchase.get("no_show_policy") or DEFAULT_NO_SHOW_POLICY):
        y = _ensure_room(y - 4, needed=80)
        y = _draw_section_header(c, page_w, y, "Missed appointment policy")
        y = _draw_wrapped_text(
            c,
            no_show_policy or purchase.get("no_show_policy") or DEFAULT_NO_SHOW_POLICY,
            x=margin, y=y, max_width=inner_w,
            page_break=_page_break, min_y=min_y,
        )

    # --- Termination + refund clause ---
    y = _ensure_room(y - 4, needed=100)
    y = _draw_section_header(c, page_w, y, "Right to terminate · refund calculation")
    y = _draw_wrapped_text(
        c,
        termination_clause or DEFAULT_TERMINATION_CLAUSE,
        x=margin, y=y, max_width=inner_w,
        page_break=_page_break, min_y=min_y,
    )

    # --- Signature block ---
    # Block needs ~90 high (two ruled lines + labels + spacer). Reserve that
    # FIRST so the signature never overlaps the termination clause above it
    # — the old code clamped sig_top to 1.4*inch which caused exactly that
    # collision when content ran long.
    y = _ensure_room(y - 18, needed=100)
    _draw_signature_block(c, margin=margin, inner_w=inner_w, y_top=y)

    # No centered clinic-info footer — clinic name + address + phone are
    # already rendered in the header band at the top of every page, and the
    # bottom-right of every page carries a "Page N of M" stamp drawn by
    # NumberedCanvas. A centered footer at the same y would collide with
    # that stamp (see screenshot 2026-05-25).

    c.showPage()
    c.save()
    return out


def ensure_package_pdf(
    patient_root: str | Path,
    pdf_path: Path,
    *,
    patient_name: str,
) -> Path:
    """
    Ensure a package PDF exists at `pdf_path`, lazy-generating it if not.

    Routing (by filename prefix):
      * `package_contract_<package_id>.pdf`              → `build_contract_pdf`
      * `package_statement_<package_id>_<YYYYMMDD>.pdf`  → `build_statement_pdf`

    If the PDF already exists, returns it unchanged. If the package_id cannot
    be extracted (legacy file with no id in the name), falls back to a simple
    text-rendered PDF using the .txt sidecar via `build_pdf_from_text`.
    """
    if pdf_path.exists():
        return pdf_path

    stem = pdf_path.stem
    if stem.startswith("package_contract_"):
        package_id = stem[len("package_contract_"):]
        if package_id and find_purchase_event(patient_root, package_id):
            return build_contract_pdf(
                patient_root,
                patient_name=patient_name,
                package_id=package_id,
            )
    elif stem.startswith("package_statement_"):
        rest = stem[len("package_statement_"):]
        # rest = "<package_id>_<YYYYMMDD>" — package_id may itself contain
        # underscores so split from the RIGHT on a single underscore.
        if "_" in rest:
            package_id, _date_key = rest.rsplit("_", 1)
        else:
            package_id = rest
        if package_id and find_purchase_event(patient_root, package_id):
            return build_statement_pdf(
                patient_root,
                patient_name=patient_name,
                package_id=package_id,
            )

    # Fallback: render the .txt sidecar (if any) as a simple monospace PDF so
    # the user still gets a printable document for legacy files.
    sidecar = pdf_path.with_suffix(".txt")
    text = ""
    if sidecar.is_file():
        try:
            text = sidecar.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    if not text:
        text = (
            f"Package document\n"
            f"Patient: {patient_name}\n"
            f"(Source data was not available to regenerate this PDF.)"
        )
    from billing_pdf import build_pdf_from_text
    return build_pdf_from_text(pdf_path, text)


def build_statement_pdf(
    patient_root: str | Path,
    *,
    patient_name: str,
    package_id: str = "",
    statement_date: str = "",
) -> Path:
    """
    "Statement of Account" — itemized accounting of a single prepaid plan.

    Output content mirrors the Package detail dialog (and the .txt sidecar)
    so a printed statement contains every field the user can see in-app:
    plan summary, pricing, usage, balances, deferred revenue, therapeutic
    objectives, and the full chronological event log.

    File naming: `package_statement_<pkg_id>_<YYYYMMDD>.pdf` — one per day per
    package, so re-printing the same day overwrites (no clutter), but the next
    day produces a fresh dated snapshot for audit trail purposes.

    A .txt sidecar with the same stem is always written alongside the .pdf
    so the Receipt folder dialog can preview the statement inline without
    needing to read the binary PDF.
    """
    _require_reportlab()

    now = datetime.now()
    issued_label = statement_date or now.strftime("%m/%d/%Y %I:%M %p")
    date_key = now.strftime("%Y%m%d")
    # Statement is per-package, per-day. The "all packages summary" mode is
    # not used in the current UI; require a package_id for sane file naming.
    if not package_id:
        # Fall back to a global stem so callers without a package_id (legacy)
        # still get a unique file. Date keeps it from clobbering history.
        unique_key = f"all_{date_key}"
    else:
        unique_key = f"{package_id}_{date_key}"
    out = _new_receipt_path(
        patient_root,
        prefix="package_statement",
        subfolder="package",
        unique_key=unique_key,
    )

    # ---- Always write the .txt sidecar (single source of truth) ----
    sidecar = out.with_suffix(".txt")
    if package_id:
        text = build_package_statement_text(
            patient_root,
            patient_name=patient_name,
            package_id=package_id,
            statement_date=issued_label,
        )
    else:
        # Aggregate text (multi-package mode) — minimal fallback for legacy use.
        text = (
            f"STATEMENT OF ACCOUNT — ALL PREPAID PLANS\n"
            f"========================================\n"
            f"Patient: {patient_name}\n"
            f"Issued:  {issued_label}\n"
        )
    try:
        sidecar.write_text(text, encoding="utf-8")
    except OSError:
        pass  # PDF generation must still succeed even if sidecar write fails.

    # ---- PDF rendering ----
    c = _new_pdf_canvas(out, pagesize=LETTER)
    page_w, page_h = LETTER
    margin = 0.55 * inch
    inner_w = page_w - 2 * margin

    y = _draw_header_band(c, page_w, page_h)
    y = _draw_title_block(
        c, page_w, y,
        title="Statement of Account — Prepaid Plan",
        subtitle="Itemized accounting of package purchase, visits, payments, and balance",
    )

    events = load_package_log(patient_root).get("events") or []
    by_pkg: dict[str, list[dict]] = {}
    for e in events:
        pid = e.get("package_id") or ""
        if not pid:
            continue
        if package_id and pid != package_id:
            continue
        by_pkg.setdefault(pid, []).append(e)

    if not by_pkg:
        c.setFont("Helvetica", 11)
        c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
        c.drawString(margin, y - 20, "No package activity for this patient.")
        c.showPage()
        c.save()
        return out

    y -= 8
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.HexColor(COLOR_PRIMARY))
    c.drawString(margin, y, f"Patient: {patient_name}")
    c.drawRightString(page_w - margin, y, f"Issued: {issued_label}")
    y -= 18

    def _ensure_room(canvas_: "pdf_canvas.Canvas", current_y: float, needed: float = 60) -> float:
        if current_y - needed < 1.0 * inch:
            canvas_.showPage()
            return page_h - margin - 16
        return current_y

    for pid, evs in by_pkg.items():
        state = compute_package_state(evs)
        purchase = state.get("purchase") or {}

        # Section header: plan name + status
        y = _ensure_room(c, y, 200)
        y = _draw_section_header(
            c, page_w, y,
            f"{purchase.get('name') or 'Package'}  ({status_label(state.get('status') or '')})",
        )

        # --- Plan summary ---
        y = _draw_kv_row(c, x=margin, y=y, label="Package ID", value=pid)
        y = _draw_kv_row(c, x=margin, y=y, label="Catalog template",
                         value=purchase.get("catalog_id") or "(ad-hoc)")
        y = _draw_kv_row(c, x=margin, y=y, label="Plan name", value=purchase.get("name") or "")
        y = _draw_kv_row(c, x=margin, y=y, label="Purchase date",
                         value=purchase.get("purchase_date") or "")
        y = _draw_kv_row(c, x=margin, y=y, label="Expiration",
                         value=purchase.get("expiration_date") or "(none)")
        y = _draw_kv_row(c, x=margin, y=y, label="Total visits",
                         value=str(purchase.get("total_visits") or 0))
        y = _draw_kv_row(c, x=margin, y=y, label="CPT whitelist",
                         value=", ".join(str(cpt) for cpt in (purchase.get("cpt_whitelist") or [])))
        y = _draw_kv_row(c, x=margin, y=y, label="Purchase price",
                         value=f"${float(purchase.get('purchase_price') or 0):,.2f}")
        y = _draw_kv_row(c, x=margin, y=y, label="Pro-rata per visit",
                         value=f"${float(purchase.get('prorated_value_per_visit') or 0):,.2f}")

        # --- PAYMENT STATUS (prominent) ---
        y -= 6
        y = _ensure_room(c, y, 90)
        y = _draw_section_header(c, page_w, y, "Payment status")
        purchase_price = float(purchase.get("purchase_price") or 0)
        amount_paid = float(state.get("amount_paid") or 0)
        balance_due = float(state.get("purchase_balance_due") or 0)
        y = _draw_kv_row(c, x=margin, y=y, label="Purchase price",
                         value=f"${purchase_price:,.2f}")
        y = _draw_kv_row(c, x=margin, y=y, label="Amount paid (so far)",
                         value=f"${amount_paid:,.2f}")
        # Bold, highlighted balance line so PAID IN FULL or REMAINING TO PAY
        # is unmissable when the receipt is scanned at a glance.
        bal_label_y = y
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
        c.drawString(margin, bal_label_y, "Balance")
        c.setFont("Helvetica-Bold", 11)
        if state.get("is_paid_in_full"):
            c.setFillColor(colors.HexColor("#047857"))  # emerald — paid in full
            c.drawString(margin + 130, bal_label_y, "PAID IN FULL")
        else:
            c.setFillColor(colors.HexColor("#B91C1C"))  # red-700 — owed
            c.drawString(
                margin + 130, bal_label_y,
                f"${balance_due:,.2f}   (REMAINING TO PAY)",
            )
        y -= 18

        # --- Visits & deferred revenue ---
        y -= 4
        y = _ensure_room(c, y, 100)
        y = _draw_section_header(c, page_w, y, "Visits & deferred revenue")
        y = _draw_kv_row(c, x=margin, y=y, label="Visits used",
                         value=str(state.get("visits_used") or 0))
        y = _draw_kv_row(c, x=margin, y=y, label="Visits remaining",
                         value=str(state.get("visits_remaining") or 0))
        y = _draw_kv_row(c, x=margin, y=y, label="Revenue recognized",
                         value=f"${float(state.get('value_recognized') or 0):,.2f}")
        y = _draw_kv_row(c, x=margin, y=y, label="Refunds paid",
                         value=f"${float(state.get('refund_paid') or 0):,.2f}")
        y = _draw_kv_row(c, x=margin, y=y, label="Deferred remaining",
                         value=f"${float(state.get('deferred_revenue_remaining') or 0):,.2f}")

        # --- Therapeutic objectives ---
        objectives = (purchase.get("therapeutic_objectives") or "").strip()
        if objectives:
            y -= 4
            y = _ensure_room(c, y, 60)
            y = _draw_section_header(c, page_w, y, "Therapeutic objectives")
            y = _draw_wrapped_text(c, objectives, x=margin, y=y, max_width=inner_w)

        # --- Event log (full audit trail) ---
        y -= 4
        y = _ensure_room(c, y, 80)
        y = _draw_section_header(c, page_w, y, "Event log  (append-only — source of truth)")
        for e in evs:
            y = _ensure_room(c, y, 24)
            # Re-assert font + color INSIDE the loop: `_ensure_room()` may
            # have just called showPage(), which resets the canvas state to
            # ReportLab's defaults (Helvetica 12, black). Without this, page
            # 2's event-log lines render in a larger font than page 1.
            c.setFont("Helvetica", 9)
            c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
            ts = (e.get("timestamp") or "").replace("T", " ")
            etype = (e.get("type") or "").upper()
            extra = ""
            if e.get("type") == "redemption":
                cpts_list = e.get("cpts_redeemed") or []
                if cpts_list:
                    cpt_label = "CPTs " + ", ".join(str(cp) for cp in cpts_list)
                else:
                    cpt_label = f"CPT {e.get('cpt_redeemed') or ''}"
                extra = (
                    f" · {cpt_label}"
                    f" · ${float(e.get('value_recognized') or 0):,.2f}"
                    f" · DOS {e.get('date_of_service') or ''}"
                )
            elif e.get("type") == "refund":
                extra = (
                    f" · ${float(e.get('amount') or 0):,.2f}"
                    f" · {e.get('method') or ''}"
                    f" · strategy: {e.get('refund_strategy') or ''}"
                )
            elif e.get("type") == "cancellation":
                extra = f" · {(e.get('reason') or '')[:60]}"
            elif e.get("type") == "payment":
                extra = (
                    f" · ${float(e.get('amount') or 0):,.2f}"
                    f" · {e.get('method') or ''}"
                    f" · {e.get('payment_date') or ''}"
                )
            line = f"  {ts}  {etype}{extra}"
            c.drawString(margin, y, line[:170])
            y -= 12

        y -= 12

    # No clinic-info footer here — clinic name + address are already
    # rendered in the header band at the top of every page, and the
    # bottom-right of every page now carries a "Page N of M" stamp drawn
    # by NumberedCanvas. Keeping a centered clinic line at the same y
    # would visually collide with that page-number text (see screenshot
    # 2026-05-25: "Phase 19f 2" overlap).
    c.showPage()
    c.save()
    return out
