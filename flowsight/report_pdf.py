# =============================================================================
# report_pdf.py — FlowSight PDF Report Generator  v2.0
# Professional layout — works for retail, restaurant, wine, exhibition, cafe
# =============================================================================
import sqlite3, os
from datetime import datetime
from pathlib import Path

TZ = 7

def query(conn, sql, p=()):
    try:
        return conn.execute(sql, p).fetchall()
    except Exception:
        return []

def build_pdf(db_path: str, date_filter: str = None, out_path: str = None):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable,
                                    BaseDocTemplate, Frame, PageTemplate)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

    # ── Database queries ──────────────────────────────────────────────────────
    conn = sqlite3.connect(db_path)
    dc   = f"date(datetime(timestamp,'unixepoch','+{TZ} hours'))"
    wh   = f"AND {dc}=?" if date_filter else ""
    p    = (date_filter,) if date_filter else ()

    try:
        total = query(conn, f"SELECT COUNT(*) FROM events WHERE is_new_visit=1 {wh}", p)[0][0]
        if total == 0:
            total = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE 1=1 {wh}", p)[0][0]
    except Exception:
        total = 0

    try:
        inter = query(conn, f"""SELECT COUNT(DISTINCT person_id) FROM events
            WHERE (behavior_id LIKE '%interest%' OR behavior_id='interested'
                   OR behavior_id LIKE '%tasting%' OR behavior_id LIKE '%viewing%'
                   OR behavior_id LIKE '%engaged%') {wh}""", p)[0][0]
    except Exception:
        inter = 0

    try:
        purch = query(conn, f"""SELECT COUNT(DISTINCT person_id) FROM events
            WHERE (behavior_id LIKE '%checkout%' OR behavior_id='checkout_ready'
                   OR behavior_id='purchasing') {wh}""", p)[0][0]
    except Exception:
        purch = 0

    alrt = query(conn, f"SELECT COUNT(*) FROM events WHERE needs_staff=1 {wh}", p)[0][0]

    top_z = query(conn, f"""SELECT zone_name, COUNT(*) n FROM events
        WHERE zone!='floor' AND zone_name!='' {wh}
        GROUP BY zone_name ORDER BY n DESC LIMIT 1""", p)
    if not top_z:
        top_z = query(conn, f"""SELECT zone, COUNT(*) n FROM events
            WHERE zone!='floor' {wh} GROUP BY zone ORDER BY n DESC LIMIT 1""", p)

    dr = query(conn, f"""SELECT
        MIN(strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours'))),
        MAX(strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours'))),
        {dc} FROM events WHERE 1=1 {wh}""", p)
    dr = dr[0] if dr else (None, None, None)

    hourly = query(conn, f"""SELECT
        strftime('%H',datetime(timestamp,'unixepoch','+{TZ} hours')) hr,
        COUNT(DISTINCT person_id) n
        FROM events WHERE 1=1 {wh} GROUP BY hr ORDER BY hr""", p)

    try:
        behs = query(conn, f"""SELECT behavior_name, COUNT(*) n FROM events
            WHERE behavior_name!='' {wh} GROUP BY behavior_name ORDER BY n DESC""", p)
        if not behs:
            behs = query(conn, f"""SELECT behavior, COUNT(*) n FROM events
                WHERE 1=1 {wh} GROUP BY behavior ORDER BY n DESC""", p)
    except Exception:
        behs = []

    try:
        zones = query(conn, f"""SELECT zone_name, COUNT(*) n FROM events
            WHERE zone!='floor' AND zone_name!='' {wh}
            GROUP BY zone_name ORDER BY n DESC LIMIT 10""", p)
        if not zones:
            zones = query(conn, f"""SELECT zone, COUNT(*) n FROM events
                WHERE zone!='floor' {wh} GROUP BY zone ORDER BY n DESC LIMIT 10""", p)
    except Exception:
        zones = []

    try:
        tl = query(conn, f"""SELECT
            strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours')),
            person_id, zone_name, behavior_name
            FROM events WHERE needs_staff=1 {wh}
            ORDER BY timestamp DESC LIMIT 25""", p)
        if not tl:
            tl = query(conn, f"""SELECT
                strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours')),
                person_id, zone, behavior
                FROM events WHERE needs_staff=1 {wh}
                ORDER BY timestamp DESC LIMIT 25""", p)
    except Exception:
        tl = []

    conn.close()

    rep_date = dr[2] or date_filter or datetime.now().strftime("%Y-%m-%d")
    t_start  = dr[0] or "—"
    t_end    = dr[1] or "—"
    if not out_path:
        out_path = f"flowsight_report_{rep_date}.pdf"

    # ── Colours — AA & CC / FlowSight brand palette ─────────────────────────
    # Primary brand
    TEAL      = colors.HexColor("#1a5f7a")   # FlowSight teal (brand dark)
    TEAL_LT   = colors.HexColor("#e0f4f8")   # teal tint background
    GOLD      = colors.HexColor("#d4a800")   # accent gold
    GOLD_LT   = colors.HexColor("#fef9e0")   # gold tint background
    GOLD_MID  = colors.HexColor("#e8bc00")   # accent gold mid

    # Backgrounds & surfaces (warm stone grays)
    BG        = colors.HexColor("#c8c8be")   # page background
    SURFACE   = colors.HexColor("#d8d8ce")   # card surface
    SURFACE2  = colors.HexColor("#c0c0b6")   # section header surface
    BORDER    = colors.HexColor("#b0b0a6")   # border
    DARK      = colors.HexColor("#2a2a28")   # primary text
    MUTED     = colors.HexColor("#6a6a62")   # muted text
    CHARCOAL  = colors.HexColor("#3a3a36")   # dark nav / header bg

    # Semantic colours (kept readable on light bg)
    GREEN     = colors.HexColor("#16a34a")
    GREEN_LT  = colors.HexColor("#dcfce7")
    AMBER     = colors.HexColor("#c47a00")
    AMBER_LT  = colors.HexColor("#fef3c7")
    RED       = colors.HexColor("#c0392b")
    RED_LT    = colors.HexColor("#fee2e2")
    BLUE      = colors.HexColor("#1a6fa8")
    BLUE_LT   = colors.HexColor("#dbeafe")
    WHITE     = colors.white

    # Aliases to keep old references working
    INDIGO    = TEAL
    INDIGO_LT = TEAL_LT
    SLATE     = CHARCOAL
    GRAY      = MUTED
    LGRAY     = SURFACE
    MGRAY     = BORDER
    DGRAY     = DARK

    PAGE_W, PAGE_H = A4
    ML = MR = 1.8 * cm
    MT = 1.5 * cm
    MB = 1.2 * cm
    CW = PAGE_W - ML - MR
    HEADER_H = 1.4 * cm
    FOOTER_H = 1.0 * cm

    # ── Page chrome ───────────────────────────────────────────────────────────
    class FlowDoc(BaseDocTemplate):
        def __init__(self, filename, **kw):
            super().__init__(filename, **kw)
            frame = Frame(ML, MB + FOOTER_H + 2*mm,
                          CW, PAGE_H - MT - MB - HEADER_H - FOOTER_H - 4*mm,
                          id="main", leftPadding=0, rightPadding=0,
                          topPadding=0, bottomPadding=0)
            self.addPageTemplates([PageTemplate(id="main", frames=frame,
                                                onPage=self._chrome)])

        def _chrome(self, cvs, doc):
            cvs.saveState()
            # ── Header — FlowSight teal bar with gold accent ─────────────────
            cvs.setFillColor(CHARCOAL)
            cvs.rect(0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, fill=1, stroke=0)
            # Gold accent left strip
            cvs.setFillColor(GOLD)
            cvs.rect(0, PAGE_H - HEADER_H, 5*mm, HEADER_H, fill=1, stroke=0)
            # Gold bottom edge line
            cvs.setStrokeColor(GOLD)
            cvs.setLineWidth(1.0)
            cvs.line(0, PAGE_H - HEADER_H, PAGE_W, PAGE_H - HEADER_H)
            cvs.setFillColor(GOLD)
            cvs.setFont("Helvetica-Bold", 10)
            cvs.drawString(ML + 6*mm, PAGE_H - 0.88*cm, "FLOWSIGHT")
            cvs.setFont("Helvetica", 9)
            cvs.setFillColor(colors.HexColor("#b0a888"))
            cvs.drawString(ML + 6*mm + 72, PAGE_H - 0.88*cm,
                           "Daily Activity Report")
            cvs.setFillColor(colors.HexColor("#b0a888"))
            cvs.setFont("Helvetica", 8.5)
            cvs.drawRightString(PAGE_W - MR, PAGE_H - 0.88*cm,
                                f"Date: {rep_date}")
            # ── Footer — warm surface with gold separator line ────────────────
            cvs.setFillColor(SURFACE)
            cvs.rect(0, 0, PAGE_W, FOOTER_H, fill=1, stroke=0)
            cvs.setStrokeColor(GOLD)
            cvs.setLineWidth(0.8)
            cvs.line(0, FOOTER_H, PAGE_W, FOOTER_H)
            cvs.setFillColor(MUTED)
            cvs.setFont("Helvetica", 7.5)
            cvs.drawString(ML, 0.35*cm,
                "FlowSight — Platform for Flow and Insight Behavior Tracking  ·  AA & CC  ·  ISO/IEC 29110:2024")
            cvs.setFillColor(DARK)
            cvs.setFont("Helvetica-Bold", 8)
            cvs.drawRightString(PAGE_W - MR, 0.35*cm, f"Page {doc.page}")
            cvs.restoreState()

    # ── Style factory ─────────────────────────────────────────────────────────
    def S(name, **kw):
        return ParagraphStyle(name, **kw)

    story = []

    # ── Section header ────────────────────────────────────────────────────────
    def section(title, subtitle=""):
        # Accent line + title bar
        t = Table(
            [[Paragraph(f"<b>{title}</b>",
               S("sh", fontName="Helvetica-Bold", fontSize=10,
                 textColor=WHITE, leading=14))]],
            colWidths=[CW]
        )
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), CHARCOAL),
            ("TOPPADDING",    (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
            ("RIGHTPADDING",  (0,0), (-1,-1), 10),
            ("LINEBELOW",     (0,-1),(-1,-1), 2.0, GOLD),
        ]))
        story.append(t)
        if subtitle:
            story.append(Paragraph(subtitle,
                S("sst", fontName="Helvetica-Oblique", fontSize=8,
                  textColor=GRAY, spaceBefore=3, spaceAfter=6)))
        else:
            story.append(Spacer(1, 6))

    # ── KPI row (flat, no nested tables) ──────────────────────────────────────
    def kpi_row(items):
        """items = list of (label, value, bg_hex, text_hex)"""
        n  = len(items)
        cw = CW / n

        header_row = []
        value_row  = []
        label_row  = []

        for label, value, bg, tc in items:
            header_row.append(Paragraph("", S("_", fontSize=1)))
            value_row.append(
                Paragraph(f"<b>{value}</b>",
                    S("kv", fontName="Helvetica-Bold", fontSize=22,
                      textColor=colors.HexColor(tc),
                      alignment=TA_CENTER, leading=28))
            )
            label_row.append(
                Paragraph(label,
                    S("kl", fontName="Helvetica", fontSize=8,
                      textColor=GRAY, alignment=TA_CENTER, leading=11))
            )

        data   = [value_row, label_row]
        widths = [cw] * n

        ts = TableStyle([
            ("TOPPADDING",    (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
            ("LEFTPADDING",   (0,0), (-1,-1), 4),
            ("RIGHTPADDING",  (0,0), (-1,-1), 4),
            ("TOPPADDING",    (0,0), (-1,0),  14),
            ("BOTTOMPADDING", (0,0), (-1,0),  4),
            ("TOPPADDING",    (0,1), (-1,1),  0),
            ("BOTTOMPADDING", (0,1), (-1,1),  14),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("BOX",           (0,0), (-1,-1), 0.5, MGRAY),
            ("LINEAFTER",     (0,0), (-2,-1), 0.5, MGRAY),
        ])
        for i, (_, _, bg, _) in enumerate(items):
            ts.add("BACKGROUND", (i,0), (i,-1), colors.HexColor(bg))

        t = Table(data, colWidths=widths)
        t.setStyle(ts)
        story.append(t)
        story.append(Spacer(1, 10))

    # ── Professional data table ───────────────────────────────────────────────
    def data_table(headers, rows, widths, aligns=None):
        if not rows:
            story.append(Paragraph("No data available for this period.",
                S("nd", fontName="Helvetica-Oblique", fontSize=8.5,
                  textColor=GRAY, spaceAfter=10)))
            return

        data = [headers] + rows
        ts = TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  CHARCOAL),
            ("TEXTCOLOR",     (0,0), (-1,0),  colors.HexColor("#e8dfc0")),
            ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE",      (0,0), (-1,-1), 8.5),
            ("TOPPADDING",    (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
            ("LEFTPADDING",   (0,0), (-1,-1), 9),
            ("RIGHTPADDING",  (0,0), (-1,-1), 9),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, SURFACE]),
            ("LINEBELOW",     (0,0), (-1,-2), 0.3, BORDER),
            ("LINEBELOW",     (0,-1),(-1,-1), 0.8, BORDER),
            ("BOX",           (0,0), (-1,-1), 0.8, BORDER),
            ("ALIGN",         (0,0), (-1,0),  "CENTER"),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ])
        if aligns:
            for ci, al in enumerate(aligns):
                ts.add("ALIGN", (ci,1), (ci,-1), al)

        t = Table(data, colWidths=widths)
        t.setStyle(ts)
        story.append(t)
        story.append(Spacer(1, 10))

    # ── Mini bar chart ────────────────────────────────────────────────────────
    def bar(val, max_val, color="#1a5f7a"):
        pct = min(val / max_val, 1.0) if max_val else 0
        n   = int(pct * 18)
        return Paragraph(
            f'<font color="{color}">{"█" * n}</font>'
            f'<font color="#DDDDDD">{"░" * (18-n)}</font>',
            S("bar", fontName="Helvetica", fontSize=7, leading=10))

    # ══════════════════════════════════════════════════════════════════════════
    # COVER PAGE
    # ══════════════════════════════════════════════════════════════════════════
    now_str = datetime.now().strftime("%d %B %Y, %H:%M")

    cover_data = [
        [Paragraph("FLOWSIGHT",
            S("ct", fontName="Helvetica-Bold", fontSize=30,
              textColor=GOLD, alignment=TA_CENTER, leading=38))],
        [Paragraph("Platform for Flow and Insight Behavior Tracking",
            S("cs", fontName="Helvetica", fontSize=11,
              textColor=colors.HexColor("#b0a888"),
              alignment=TA_CENTER, leading=18))],
        [Spacer(1, 8)],
        [HRFlowable(width=CW * 0.4, color=GOLD,
                    thickness=2.0, spaceAfter=8)],
        [Paragraph("Daily Activity Report",
            S("cr", fontName="Helvetica-Bold", fontSize=16,
              textColor=WHITE, alignment=TA_CENTER, leading=22))],
        [Spacer(1, 4)],
        [Paragraph(f"Date: {rep_date}",
            S("cd", fontName="Helvetica", fontSize=11,
              textColor=colors.HexColor("#e8dfc0"),
              alignment=TA_CENTER, leading=16))],
        [Paragraph(f"Period: {t_start} – {t_end}",
            S("cp", fontName="Helvetica", fontSize=10,
              textColor=colors.HexColor("#b0a888"),
              alignment=TA_CENTER, leading=14))],
        [Spacer(1, 6)],
        [Paragraph(f"Generated: {now_str}",
            S("cg", fontName="Helvetica-Oblique", fontSize=9,
              textColor=colors.HexColor("#7a7a72"),
              alignment=TA_CENTER, leading=13))],
    ]

    cover = Table(cover_data, colWidths=[CW])
    cover.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), CHARCOAL),
        ("TOPPADDING",    (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ("LEFTPADDING",   (0,0), (-1,-1), 20),
        ("RIGHTPADDING",  (0,0), (-1,-1), 20),
        ("TOPPADDING",    (0,0), (0,0),   36),
        ("BOTTOMPADDING", (0,-1),(0,-1),  36),
        ("TOPPADDING",    (0,3), (0,3),   0),
        ("BOTTOMPADDING", (0,3), (0,3),   0),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
    ]))
    story.append(cover)
    story.append(Spacer(1, 20))

    # ══════════════════════════════════════════════════════════════════════════
    # KPI SECTION
    # ══════════════════════════════════════════════════════════════════════════
    section("KEY PERFORMANCE INDICATORS", "Summary for the reporting period")

    kpi_row([
        ("Total Visitors",  str(total), "#dbeafe", "#1a6fa8"),
        ("Showed Interest", str(inter),  "#fef3c7", "#c47a00"),
        ("At Counter",      str(purch),  "#dcfce7", "#16a34a"),
        ("Staff Alerts",    str(alrt),   "#fee2e2", "#c0392b"),
        ("Top Zone", (top_z[0][0] if top_z else "—"), "#fef9e0", "#d4a800"),
    ])

    conv = round(inter / total * 100, 1) if total else 0
    pr   = round(purch / total * 100, 1) if total else 0

    # Insight box
    insight_text = (
        f"<b>Summary:</b> {total:,} visitors detected today. "
        f"<b>{inter:,}</b> ({conv}%) showed product interest. "
        f"<b>{purch:,}</b> ({pr}%) reached the checkout. "
        f"<b>{alrt}</b> staff alert{'s' if alrt != 1 else ''} triggered."
    )
    ins = Table([[Paragraph(insight_text,
        S("ins", fontName="Helvetica", fontSize=9, textColor=DARK,
          leading=14))]],
        colWidths=[CW])
    ins.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), GOLD_LT),
        ("TOPPADDING",    (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("LEFTPADDING",   (0,0), (-1,-1), 12),
        ("RIGHTPADDING",  (0,0), (-1,-1), 12),
        ("BOX",           (0,0), (-1,-1), 0.5, GOLD),
        ("LINEABOVE",     (0,0), (-1,0),  2.0, GOLD),
    ]))
    story.append(ins)
    story.append(Spacer(1, 16))

    # ══════════════════════════════════════════════════════════════════════════
    # HOURLY TRAFFIC
    # ══════════════════════════════════════════════════════════════════════════
    section("HOURLY VISITOR TRAFFIC")
    if hourly:
        max_h = max(r[1] for r in hourly) or 1
        peak  = max(hourly, key=lambda r: r[1])
        rows  = []
        for hr_val, cnt in hourly:
            is_pk = hr_val == peak[0]
            fc    = TEAL if is_pk else DARK
            fn    = "Helvetica-Bold" if is_pk else "Helvetica"
            rows.append([
                Paragraph(f"{hr_val}:00",
                    S("h", fontName=fn, fontSize=9,
                      textColor=fc, alignment=TA_CENTER)),
                Paragraph(str(cnt),
                    S("c", fontName=fn, fontSize=9,
                      textColor=fc, alignment=TA_CENTER)),
                bar(cnt, max_h, "#1a5f7a"),
                Paragraph(f"{'★ PEAK  ' if is_pk else ''}{cnt/max_h*100:.0f}%",
                    S("p", fontName=fn, fontSize=8,
                      textColor=GOLD if is_pk else MUTED,
                      alignment=TA_RIGHT)),
            ])
        data_table(
            ["Hour", "Visitors", "Traffic", "% of Peak"],
            rows,
            [CW*.12, CW*.12, CW*.56, CW*.20],
            aligns=["CENTER","CENTER","LEFT","RIGHT"]
        )
        story.append(Paragraph(
            f"<b>Peak hour:</b> {peak[0]}:00 with {peak[1]:,} visitors.",
            S("nt", fontName="Helvetica-Oblique", fontSize=8,
              textColor=GRAY, spaceAfter=10)))
    else:
        story.append(Paragraph("No hourly data available.",
            S("nd", fontName="Helvetica-Oblique", fontSize=8.5,
              textColor=GRAY, spaceAfter=10)))
    story.append(Spacer(1, 14))

    # ══════════════════════════════════════════════════════════════════════════
    # BEHAVIOR BREAKDOWN
    # ══════════════════════════════════════════════════════════════════════════
    section("BEHAVIOR BREAKDOWN")
    if behs:
        total_ev = sum(r[1] for r in behs) or 1
        ALERT_IDS = {"interested","loitering","checkout_ready","waiting",
                     "purchasing","long_queue","queue_alert","need_help",
                     "long_stay","long_seated","crowded","blocking"}
        rows = []
        for beh, cnt in behs:
            beh_id   = beh.lower().replace(" ","_")
            is_alert = any(a in beh_id for a in ALERT_IDS)
            pct      = cnt / total_ev * 100
            col      = "#c0392b" if is_alert else "#1a5f7a"
            rows.append([
                Paragraph(beh,
                    S("bn", fontName="Helvetica", fontSize=9, textColor=DARK)),
                Paragraph(f"{cnt:,}",
                    S("bc", fontName="Helvetica-Bold", fontSize=9,
                      textColor=DARK, alignment=TA_CENTER)),
                bar(cnt, total_ev, col),
                Paragraph(f"{pct:.1f}%",
                    S("bp", fontName="Helvetica", fontSize=9,
                      textColor=DARK, alignment=TA_CENTER)),
                Paragraph(
                    '<b>⚠ Alert</b>' if is_alert else "—",
                    S("ba", fontName="Helvetica-Bold" if is_alert else "Helvetica",
                      fontSize=8,
                      textColor=RED if is_alert else GRAY,
                      alignment=TA_CENTER)),
            ])
        data_table(
            ["Behavior", "Events", "Distribution", "Share", "Type"],
            rows,
            [CW*.28, CW*.12, CW*.33, CW*.13, CW*.14],
            aligns=["LEFT","CENTER","LEFT","CENTER","CENTER"]
        )
    else:
        story.append(Paragraph("No behavior data available.",
            S("nd", fontName="Helvetica-Oblique", fontSize=8.5,
              textColor=GRAY, spaceAfter=10)))
    story.append(Spacer(1, 14))

    # ══════════════════════════════════════════════════════════════════════════
    # ZONE ACTIVITY
    # ══════════════════════════════════════════════════════════════════════════
    section("ZONE ACTIVITY")
    if zones:
        max_z = zones[0][1] or 1
        tot_z = sum(r[1] for r in zones)
        rows  = []
        for i, (zn, cnt) in enumerate(zones):
            rows.append([
                Paragraph(str(i+1),
                    S("rk", fontName="Helvetica-Bold", fontSize=10,
                      textColor=TEAL, alignment=TA_CENTER)),
                Paragraph(zn or "—",
                    S("zn", fontName="Helvetica", fontSize=9, textColor=DARK)),
                Paragraph(f"{cnt:,}",
                    S("zc", fontName="Helvetica-Bold", fontSize=9,
                      textColor=DARK, alignment=TA_CENTER)),
                bar(cnt, max_z, "#1a5f7a"),
                Paragraph(f"{cnt/tot_z*100:.1f}%",
                    S("zp", fontName="Helvetica", fontSize=9,
                      textColor=DARK, alignment=TA_CENTER)),
            ])
        data_table(
            ["Rank", "Zone Name", "Events", "Activity", "Share"],
            rows,
            [CW*.07, CW*.30, CW*.11, CW*.35, CW*.17],
            aligns=["CENTER","LEFT","CENTER","LEFT","CENTER"]
        )
    else:
        story.append(Paragraph("No zone data available.",
            S("nd", fontName="Helvetica-Oblique", fontSize=8.5,
              textColor=GRAY, spaceAfter=10)))
    story.append(Spacer(1, 14))

    # ══════════════════════════════════════════════════════════════════════════
    # STAFF ALERT TIMELINE
    # ══════════════════════════════════════════════════════════════════════════
    section("STAFF ALERT TIMELINE")
    if tl:
        rows = []
        URGENT = {"loitering","waiting_too_long","waiting","long_queue",
                  "queue_alert","need_help","long_stay","blocking","crowded"}
        for row in tl:
            t_val, pid, zone_val, beh_val = row
            beh_id = (beh_val or "").lower().replace(" ","_")
            is_urg = any(u in beh_id for u in URGENT)
            tc     = RED if is_urg else AMBER
            rows.append([
                Paragraph(t_val or "—",
                    S("tt", fontName="Helvetica-Bold", fontSize=9,
                      textColor=DARK, alignment=TA_CENTER)),
                Paragraph(f"#{pid}",
                    S("tp", fontName="Helvetica", fontSize=9,
                      textColor=DARK, alignment=TA_CENTER)),
                Paragraph(zone_val or "—",
                    S("tz", fontName="Helvetica", fontSize=9, textColor=DARK)),
                Paragraph(f"<b>{beh_val or '—'}</b>",
                    S("tb", fontName="Helvetica-Bold", fontSize=9, textColor=tc)),
                Paragraph(
                    '<b>URGENT</b>' if is_urg else 'Alert',
                    S("tp2", fontName="Helvetica-Bold", fontSize=8,
                      textColor=RED if is_urg else AMBER,
                      alignment=TA_CENTER)),
            ])
        data_table(
            ["Time", "Person", "Zone", "Behavior", "Priority"],
            rows,
            [CW*.12, CW*.10, CW*.28, CW*.33, CW*.17],
            aligns=["CENTER","CENTER","LEFT","LEFT","CENTER"]
        )
    else:
        story.append(Paragraph("No staff alerts recorded for this period.",
            S("nd", fontName="Helvetica-Oblique", fontSize=8.5,
              textColor=GRAY, spaceAfter=10)))
    story.append(Spacer(1, 14))

    # ══════════════════════════════════════════════════════════════════════════
    # AI INSIGHT (optional)
    # ══════════════════════════════════════════════════════════════════════════
    try:
        from ai_insight import get_ai_insight
        ai_res      = get_ai_insight(db_path, date_filter, api_key="")
        insight_txt = ai_res.get("insight") or ai_res.get("fallback","")
        if insight_txt:
            section("DAILY INSIGHT & RECOMMENDATIONS",
                    ai_res.get("source","Automated Analysis"))
            for line in insight_txt.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("**") and line.endswith("**"):
                    story.append(Paragraph(line.strip("*"),
                        S("it", fontName="Helvetica-Bold", fontSize=10,
                          textColor=TEAL, spaceBefore=8, spaceAfter=3)))
                elif line and len(line)>1 and line[0].isdigit() and line[1]==".":
                    story.append(Paragraph(f"  {line}",
                        S("ir", fontName="Helvetica", fontSize=9, textColor=DARK,
                          leading=14, leftIndent=12,
                          backColor=SURFACE, borderPadding=4, spaceAfter=3)))
                else:
                    story.append(Paragraph(line.replace("**",""),
                        S("ip", fontName="Helvetica", fontSize=9, textColor=DARK,
                          leading=14, spaceAfter=2)))
    except Exception:
        pass

    # ══════════════════════════════════════════════════════════════════════════
    # FOOTER NOTE
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width=CW, color=MGRAY, thickness=0.5))
    story.append(Paragraph(
        f"Generated by FlowSight on {now_str}  ·  "
        f"Data source: {os.path.basename(db_path)}  ·  "
        f"Confidential — For internal use only",
        S("disc", fontName="Helvetica-Oblique", fontSize=7.5,
          textColor=GRAY, alignment=TA_CENTER, spaceBefore=6)))

    # ── Build ─────────────────────────────────────────────────────────────────
    doc = FlowDoc(
        out_path, pagesize=A4,
        leftMargin=ML, rightMargin=MR,
        topMargin=MT, bottomMargin=MB + FOOTER_H
    )
    doc.build(story)
    return out_path
