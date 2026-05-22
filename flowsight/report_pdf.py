# =============================================================================
# report_pdf.py — FlowSight PDF Report Generator  v1.1
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
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate

    conn = sqlite3.connect(db_path)
    dc   = f"date(datetime(timestamp,'unixepoch','+{TZ} hours'))"
    wh   = f"AND {dc}=?" if date_filter else ""
    p    = (date_filter,) if date_filter else ()

    # ── Pull data (graceful fallback for old/new DB schema) ──────────────────
    # Total customers
    try:
        total = query(conn, f"SELECT COUNT(*) FROM events WHERE is_new_visit=1 {wh}", p)[0][0]
        if total == 0:
            total = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE 1=1 {wh}", p)[0][0]
    except Exception:
        total = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE 1=1 {wh}", p)[0][0]

    # Interested — check new column first, fallback to old
    try:
        inter = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior_id='interested' {wh}", p)[0][0]
        if inter == 0:
            inter = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior='interested' {wh}", p)[0][0]
    except Exception:
        inter = 0

    # Purchasing / checkout
    try:
        purch = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior_id='checkout_ready' {wh}", p)[0][0]
        if purch == 0:
            purch = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior='purchasing' {wh}", p)[0][0]
    except Exception:
        purch = 0

    alrt = query(conn, f"SELECT COUNT(*) FROM events WHERE needs_staff=1 {wh}", p)[0][0]

    # Top zone — try zone_name first
    try:
        top_z = query(conn, f"SELECT zone_name, COUNT(*) n FROM events WHERE zone!='floor' AND zone_name!='' {wh} GROUP BY zone_name ORDER BY n DESC LIMIT 1", p)
        if not top_z:
            top_z = query(conn, f"SELECT zone, COUNT(*) n FROM events WHERE zone!='floor' {wh} GROUP BY zone ORDER BY n DESC LIMIT 1", p)
    except Exception:
        top_z = []

    dr = query(conn, f"""SELECT
        MIN(strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours'))),
        MAX(strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours'))),
        {dc} FROM events WHERE 1=1 {wh}""", p)
    dr = dr[0] if dr else (None, None, None)

    hourly = query(conn, f"""SELECT strftime('%H',datetime(timestamp,'unixepoch','+{TZ} hours')) hr,
                                    COUNT(DISTINCT person_id) n
                             FROM events WHERE 1=1 {wh} GROUP BY hr ORDER BY hr""", p)

    # Behaviors — try new columns first
    try:
        behs = query(conn, f"SELECT behavior_name, COUNT(*) n FROM events WHERE behavior_name!='' {wh} GROUP BY behavior_name ORDER BY n DESC", p)
        if not behs:
            behs = query(conn, f"SELECT behavior, COUNT(*) n FROM events WHERE 1=1 {wh} GROUP BY behavior ORDER BY n DESC", p)
    except Exception:
        behs = []

    # Zone activity
    try:
        zones = query(conn, f"SELECT zone_name, COUNT(*) n FROM events WHERE zone!='floor' AND zone_name!='' {wh} GROUP BY zone_name ORDER BY n DESC LIMIT 8", p)
        if not zones:
            zones = query(conn, f"SELECT zone, COUNT(*) n FROM events WHERE zone!='floor' {wh} GROUP BY zone ORDER BY n DESC LIMIT 8", p)
    except Exception:
        zones = []

    # Alert timeline
    try:
        tl = query(conn, f"""SELECT strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours')),
                                    person_id, zone_name, behavior_name
                             FROM events WHERE needs_staff=1 {wh}
                             ORDER BY timestamp DESC LIMIT 20""", p)
        if not tl:
            tl = query(conn, f"""SELECT strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours')),
                                        person_id, zone, behavior
                                 FROM events WHERE needs_staff=1 {wh}
                                 ORDER BY timestamp DESC LIMIT 20""", p)
    except Exception:
        tl = []

    conn.close()

    rep_date = dr[2] or date_filter or datetime.now().strftime("%Y-%m-%d")
    t_start  = dr[0] or "—"
    t_end    = dr[1] or "—"
    if not out_path:
        out_path = f"flowsight_report_{rep_date}.pdf"

    # ── Colors ────────────────────────────────────────────────────────────────
    INDIGO  = colors.HexColor("#4338CA")
    INDIGO2 = colors.HexColor("#6366F1")
    DARK    = colors.HexColor("#111827")
    GRAY    = colors.HexColor("#6B7280")
    LGRAY   = colors.HexColor("#F9FAFB")
    MGRAY   = colors.HexColor("#E5E7EB")
    GREEN   = colors.HexColor("#15803D")
    GREEN_L = colors.HexColor("#F0FDF4")
    AMBER   = colors.HexColor("#B45309")
    AMBER_L = colors.HexColor("#FFFBEB")
    RED     = colors.HexColor("#B91C1C")
    RED_L   = colors.HexColor("#FEF2F2")
    BLUE    = colors.HexColor("#1D4ED8")
    BLUE_L  = colors.HexColor("#EFF6FF")
    WHITE   = colors.white

    PAGE_W, PAGE_H = A4
    ML = MR = 1.8*cm
    MT = 1.8*cm
    MB = 1.8*cm
    CW = PAGE_W - ML - MR

    # ── Page template ─────────────────────────────────────────────────────────
    class FlowDoc(BaseDocTemplate):
        def __init__(self, filename, **kw):
            super().__init__(filename, **kw)
            frame = Frame(ML, MB+1.0*cm, CW, PAGE_H-MT-MB-1.0*cm, id="main")
            self.addPageTemplates([PageTemplate(id="main", frames=frame,
                                                onPage=self._chrome)])

        def _chrome(self, cvs, doc):
            cvs.saveState()
            # Header
            cvs.setFillColor(INDIGO)
            cvs.rect(0, PAGE_H-1.3*cm, PAGE_W, 1.3*cm, fill=1, stroke=0)
            cvs.setFillColor(WHITE)
            cvs.setFont("Helvetica-Bold", 10)
            cvs.drawString(ML, PAGE_H-0.85*cm, "FlowSight — Retail Intelligence Report")
            cvs.setFont("Helvetica", 9)
            cvs.drawRightString(PAGE_W-MR, PAGE_H-0.85*cm, f"Date: {rep_date}")
            # Footer
            cvs.setFillColor(MGRAY)
            cvs.rect(0, 0, PAGE_W, 1.0*cm, fill=1, stroke=0)
            cvs.setFillColor(GRAY)
            cvs.setFont("Helvetica", 8)
            cvs.drawString(ML, 0.35*cm, "FlowSight — Retail Intelligence Platform")
            cvs.setFont("Helvetica-Bold", 9)
            cvs.drawRightString(PAGE_W-MR, 0.35*cm, f"Page {doc.page}")
            cvs.restoreState()

    # ── Style helpers ─────────────────────────────────────────────────────────
    def S(name, **kw):
        return ParagraphStyle(name, **kw)

    T_COVER = S("cv", fontName="Helvetica-Bold", fontSize=26, textColor=WHITE, alignment=TA_CENTER, leading=32)
    T_SUB   = S("sb", fontName="Helvetica", fontSize=11, textColor=WHITE, alignment=TA_CENTER, leading=16)
    T_SEC   = S("sc", fontName="Helvetica-Bold", fontSize=12, textColor=WHITE, spaceAfter=0)
    T_BODY  = S("bd", fontName="Helvetica", fontSize=9.5, textColor=DARK, leading=14, spaceAfter=4)
    T_NOTE  = S("nt", fontName="Helvetica-Oblique", fontSize=8, textColor=GRAY, leading=12)

    story = []

    def section(title, subtitle=""):
        t = Table([[Paragraph(title, T_SEC)]], colWidths=[CW])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), INDIGO),
            ("TOPPADDING",    (0,0), (-1,-1), 9),
            ("BOTTOMPADDING", (0,0), (-1,-1), 9),
            ("LEFTPADDING",   (0,0), (-1,-1), 12),
            ("RIGHTPADDING",  (0,0), (-1,-1), 12),
        ]))
        story.append(t)
        if subtitle:
            story.append(Paragraph(subtitle, T_NOTE))
        story.append(Spacer(1, 6))

    def kpi_cards(items):
        n  = len(items)
        cw = CW / n
        def mk(label, val, bg, vc):
            return [
                Table([[Paragraph(f"<b>{val}</b>",
                    S("v", fontName="Helvetica-Bold", fontSize=26,
                      textColor=colors.HexColor(vc), alignment=TA_CENTER))]],
                    colWidths=[cw]),
                Table([[Paragraph(label,
                    S("l", fontName="Helvetica", fontSize=8,
                      textColor=GRAY, alignment=TA_CENTER))]],
                    colWidths=[cw]),
            ]
        rows_val = [[mk(l,v,bg,vc)[0] for l,v,bg,vc in items]]
        rows_lbl = [[mk(l,v,bg,vc)[1] for l,v,bg,vc in items]]
        ts = TableStyle([
            ("TOPPADDING",    (0,0),(-1,-1), 0),
            ("BOTTOMPADDING", (0,0),(-1,-1), 0),
            ("LEFTPADDING",   (0,0),(-1,-1), 0),
            ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ])
        for i,(_,_,bg,_) in enumerate(items):
            ts.add("BACKGROUND",(i,0),(i,0),colors.HexColor("#"+bg if not bg.startswith("#") else bg))
        tv = Table(rows_val, colWidths=[cw]*n); tv.setStyle(ts)
        ts2 = TableStyle(list(ts._cmds))
        for i,(_,_,bg,_) in enumerate(items):
            ts2.add("TOPPADDING",(i,0),(i,0),3)
            ts2.add("BOTTOMPADDING",(i,0),(i,0),12)
        tl = Table(rows_lbl, colWidths=[cw]*n); tl.setStyle(ts2)
        outer = Table([[tv],[tl]], colWidths=[CW])
        outer.setStyle(TableStyle([
            ("BOX",         (0,0),(-1,-1),1,MGRAY),
            ("LINEABOVE",   (0,1),(-1,1),0.5,MGRAY),
            ("TOPPADDING",  (0,0),(-1,-1),0),
            ("BOTTOMPADDING",(0,0),(-1,-1),0),
            ("LEFTPADDING", (0,0),(-1,-1),0),
            ("RIGHTPADDING",(0,0),(-1,-1),0),
        ]))
        story.append(outer)
        story.append(Spacer(1,10))

    def pro_table(headers, rows, widths, aligns=None):
        data = [headers]+rows
        ts   = TableStyle([
            ("BACKGROUND",    (0,0),(-1,0),  DARK),
            ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
            ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0,0),(-1,-1), 8.5),
            ("TOPPADDING",    (0,0),(-1,-1), 6),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
            ("LEFTPADDING",   (0,0),(-1,-1), 8),
            ("RIGHTPADDING",  (0,0),(-1,-1), 8),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE,LGRAY]),
            ("GRID",          (0,0),(-1,-1), 0.3,MGRAY),
            ("BOX",           (0,0),(-1,-1), 0.8,colors.HexColor("#CCCCCC")),
            ("ALIGN",         (0,0),(-1,0),  "CENTER"),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ])
        if aligns:
            for ci,al in enumerate(aligns):
                if al != "LEFT":
                    ts.add("ALIGN",(ci,1),(ci,-1),al)
        t = Table(data, colWidths=widths); t.setStyle(ts)
        story.append(t); story.append(Spacer(1,10))

    def bar(val, max_val, color="#4338CA"):
        pct = min(val/max_val,1.0) if max_val else 0
        n   = int(pct*20)
        col = color if color.startswith("#") else f"#{color}"
        return Paragraph(
            f'<font color="{col}"><b>{"█"*n}</b></font>'
            f'<font color="#DDDDDD">{"░"*(20-n)}</font>',
            S("bar", fontName="Helvetica", fontSize=7.5, textColor=DARK))

    # ── Cover ────────────────────────────────────────────────────────────────
    cv = Table([
        [Paragraph("FlowSight", T_COVER)],
        [Paragraph("Retail Intelligence — Daily Report", T_SUB)],
        [Paragraph(f"Date: {rep_date}  &nbsp;·&nbsp;  Period: {t_start} – {t_end}", T_SUB)],
        [Paragraph(f"Generated: {datetime.now().strftime('%d %B %Y, %H:%M')}", T_SUB)],
    ], colWidths=[CW])
    cv.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1),INDIGO),
        ("TOPPADDING",    (0,0),(0,0),  30),
        ("BOTTOMPADDING", (0,0),(0,0),  6),
        ("TOPPADDING",    (0,1),(0,3),  4),
        ("BOTTOMPADDING", (0,3),(0,3),  30),
        ("LEFTPADDING",   (0,0),(-1,-1),14),
        ("RIGHTPADDING",  (0,0),(-1,-1),14),
    ]))
    story.append(cv); story.append(Spacer(1,18))

    # ── KPI ──────────────────────────────────────────────────────────────────
    section("KEY PERFORMANCE INDICATORS", "Summary for the reporting period")
    kpi_cards([
        ("Total Customers",  str(total), "EFF6FF", "#1D4ED8"),
        ("Interested",       str(inter),  "FFFBEB", "#B45309"),
        ("At Counter",       str(purch),  "F0FDF4", "#15803D"),
        ("Staff Alerts",     str(alrt),   "FEF2F2", "#B91C1C"),
        ("Top Zone", top_z[0][0] if top_z else "—", "EEF2FF", "#4338CA"),
    ])

    conv = round(inter/total*100,1) if total else 0
    pr   = round(purch/total*100,1) if total else 0
    story.append(Paragraph(
        f"<b>Summary:</b> {total} customers detected. "
        f"{inter} ({conv}%) showed interest. "
        f"{purch} ({pr}%) reached the counter. "
        f"{alrt} staff alerts generated.",
        S("ins", fontName="Helvetica", fontSize=9, textColor=DARK,
          backColor=LGRAY, borderPadding=8, leading=14, spaceAfter=10)))
    story.append(Spacer(1,12))

    # ── Hourly ───────────────────────────────────────────────────────────────
    section("HOURLY CUSTOMER TRAFFIC")
    if hourly:
        max_h = max(r[1] for r in hourly) or 1
        peak  = max(hourly, key=lambda r: r[1])
        rows  = []
        for hr_val, cnt in hourly:
            is_pk = hr_val == peak[0]
            rows.append([
                Paragraph(f"<b>{hr_val}:00</b>" if is_pk else f"{hr_val}:00",
                    S("h", fontName="Helvetica-Bold" if is_pk else "Helvetica",
                      fontSize=9, textColor=INDIGO if is_pk else DARK, alignment=TA_CENTER)),
                Paragraph(f"<b>{cnt}</b>" if is_pk else str(cnt),
                    S("c", fontName="Helvetica-Bold" if is_pk else "Helvetica",
                      fontSize=9, textColor=INDIGO if is_pk else DARK, alignment=TA_CENTER)),
                bar(cnt, max_h),
                Paragraph(f"{'▲ PEAK  ' if is_pk else ''}{cnt/max_h*100:.0f}%",
                    S("p", fontName="Helvetica-Bold" if is_pk else "Helvetica",
                      fontSize=8, textColor=INDIGO if is_pk else GRAY, alignment=TA_RIGHT)),
            ])
        pro_table(["Hour","Customers","Traffic","% of Peak"],
                  rows, [CW*.14,CW*.14,CW*.52,CW*.20])
        story.append(Paragraph(
            f"<b>Peak hour:</b> {peak[0]}:00 with {peak[1]} customers.",T_NOTE))
    else:
        story.append(Paragraph("No hourly data available.",T_NOTE))
    story.append(Spacer(1,12))

    # ── Behaviors ────────────────────────────────────────────────────────────
    ALERT_BEHS = {"interested","loitering","checkout_ready","waiting","purchasing"}
    BEH_COLORS = {
        "Browsing":"#888888","Interested":"#f59e0b","Loitering":"#ef4444",
        "Checkout Ready":"#22c55e","Waiting Too Long":"#ef4444",
        "Staff":"#a855f7","Idle":"#555555","Moving":"#aaaaaa",
    }
    section("BEHAVIOR BREAKDOWN")
    if behs:
        total_ev = sum(r[1] for r in behs) or 1
        rows = []
        for beh, cnt in behs:
            beh_id = beh.lower().replace(" ","_").replace(" too long","_too_long")
            col    = BEH_COLORS.get(beh, "#6B7280")
            is_alrt = beh_id in ALERT_BEHS
            rows.append([
                Paragraph(f'<font color="{col}">●</font>  {beh}',
                    S("b", fontName="Helvetica", fontSize=9, textColor=DARK)),
                Paragraph(f"{cnt:,}",
                    S("n", fontName="Helvetica", fontSize=9, textColor=DARK, alignment=TA_CENTER)),
                bar(cnt, total_ev, col),
                Paragraph(f"{cnt/total_ev*100:.1f}%",
                    S("pc", fontName="Helvetica", fontSize=9, textColor=DARK, alignment=TA_CENTER)),
                Paragraph("⚠ Alert" if is_alrt else "—",
                    S("al", fontName="Helvetica-Bold" if is_alrt else "Helvetica",
                      fontSize=8, textColor=RED if is_alrt else GRAY, alignment=TA_CENTER)),
            ])
        pro_table(["Behavior","Events","Distribution","Share","Alert"],
                  rows, [CW*.30,CW*.13,CW*.31,CW*.13,CW*.13])
    story.append(Spacer(1,12))

    # ── Zone Activity ─────────────────────────────────────────────────────────
    section("ZONE ACTIVITY")
    if zones:
        max_z  = zones[0][1] or 1
        tot_z  = sum(r[1] for r in zones)
        CAT_COLORS = {"product":"#3b82f6","checkout":"#22c55e","seating":"#f59e0b",
                      "staff":"#a855f7","entrance":"#14b8a6"}
        rows = []
        for i,(zn,cnt) in enumerate(zones):
            col = "#4338CA"
            rows.append([
                Paragraph(str(i+1),
                    S("rk",fontName="Helvetica-Bold",fontSize=10,textColor=INDIGO,alignment=TA_CENTER)),
                Paragraph(zn or "—",
                    S("zn",fontName="Helvetica",fontSize=9,textColor=DARK)),
                Paragraph(f"{cnt:,}",
                    S("zc",fontName="Helvetica",fontSize=9,textColor=DARK,alignment=TA_CENTER)),
                bar(cnt, max_z, col),
                Paragraph(f"{cnt/tot_z*100:.1f}%",
                    S("zp",fontName="Helvetica",fontSize=9,textColor=DARK,alignment=TA_CENTER)),
            ])
        pro_table(["Rank","Zone","Events","Activity","Share"],
                  rows,[CW*.08,CW*.28,CW*.13,CW*.35,CW*.16])
    story.append(Spacer(1,12))

    # ── Alert Timeline ────────────────────────────────────────────────────────
    section("STAFF ALERT TIMELINE")
    if tl:
        rows = []
        for row in tl:
            t_val, pid, zone_val, beh_val = row
            beh_id = (beh_val or "").lower().replace(" ","_")
            is_urg = beh_id in ("loitering","waiting_too_long","waiting")
            tc     = RED if is_urg else AMBER
            rows.append([
                Paragraph(t_val or "—",
                    S("tt",fontName="Helvetica-Bold",fontSize=9,textColor=DARK,alignment=TA_CENTER)),
                Paragraph(f"#{pid}",
                    S("tp",fontName="Helvetica",fontSize=9,textColor=DARK,alignment=TA_CENTER)),
                Paragraph(zone_val or "—",
                    S("tz",fontName="Helvetica",fontSize=9,textColor=DARK)),
                Paragraph(f'<font color="#{tc.hexval()[2:]}"><b>{beh_val or "—"}</b></font>',
                    S("tb",fontName="Helvetica-Bold",fontSize=9,textColor=tc)),
            ])
        pro_table(["Time","Person","Zone","Behavior"],
                  rows,[CW*.15,CW*.13,CW*.38,CW*.34])
    else:
        story.append(Paragraph("No staff alerts for this period.",T_NOTE))

    # ── AI Insight ────────────────────────────────────────────────────────────
    try:
        from ai_insight import get_ai_insight, insight_to_html as i2h
        ai_res = get_ai_insight(db_path, date_filter, api_key="")
        insight_txt = ai_res.get("insight") or ai_res.get("fallback","")
        if insight_txt:
            story.append(Spacer(1,12))
            section("DAILY INSIGHT & RECOMMENDATIONS", ai_res.get("source","Automated Analysis"))
            for line in insight_txt.split("\n"):
                line = line.strip()
                if not line: continue
                if line.startswith("**") and line.endswith("**"):
                    story.append(Paragraph(line.strip("*"),
                        S("it",fontName="Helvetica-Bold",fontSize=10,textColor=INDIGO,spaceBefore=8,spaceAfter=3)))
                elif line and line[0].isdigit() and len(line)>1 and line[1]==".":
                    story.append(Paragraph(f"  {line}",
                        S("ir",fontName="Helvetica",fontSize=9,textColor=DARK,leading=14,
                          leftIndent=12,backColor=LGRAY,borderPadding=4,spaceAfter=3)))
                else:
                    story.append(Paragraph(line.replace("**",""),
                        S("ip",fontName="Helvetica",fontSize=9,textColor=DARK,leading=14,spaceAfter=2)))
    except Exception:
        pass

    # ── Footer note ───────────────────────────────────────────────────────────
    story.append(Spacer(1,16))
    story.append(HRFlowable(width=CW,color=MGRAY,thickness=0.5))
    story.append(Paragraph(
        f"Generated by FlowSight on {datetime.now().strftime('%d %B %Y at %H:%M')}. "
        f"Data: {os.path.basename(db_path)}.",
        S("disc",fontName="Helvetica-Oblique",fontSize=7.5,textColor=GRAY,alignment=TA_CENTER,spaceBefore=6)))

    doc = FlowDoc(out_path, pagesize=A4,
                  leftMargin=ML, rightMargin=MR,
                  topMargin=MT, bottomMargin=MB+1.0*cm)
    doc.build(story)
    return out_path
