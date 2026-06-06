# dashboard.py — FlowSight generic overlay
import cv2, numpy as np
from zones import get_zone_color

def draw_overlay(frame, persons, states, zones_poly, zones_meta,
                 anonymize=False, author_w=960, author_h=540) -> np.ndarray:
    fh, fw = frame.shape[:2]
    sx = fw / author_w   # scale factors from authoring → native frame resolution
    sy = fh / author_h

    overlay = frame.copy()
    for zid, poly in zones_poly.items():
        meta  = zones_meta.get(zid, {})
        col   = get_zone_color(meta)
        # Scale polygon from authoring space to native frame space
        scaled = (poly.astype(float) * [sx, sy]).astype('int32')
        cv2.fillPoly(overlay, [scaled], col)
        cv2.polylines(overlay, [scaled], True, col, 2)
        cx = int(scaled.mean(0)[0])
        cy = int(scaled.mean(0)[1])
        cv2.putText(overlay, meta.get("name", zid),
                    (cx-40, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1)
    cv2.addWeighted(overlay, 0.18, frame, 0.82, 0, frame)

    for p in persons:
        state = states.get(p["state_key"])
        if state is None: continue
        x1, y1, x2, y2 = p["bbox"]

        # hex color → BGR
        hex_c = state.color.lstrip("#")
        try:
            r,g,b = int(hex_c[0:2],16),int(hex_c[2:4],16),int(hex_c[4:6],16)
            col = (b, g, r)
        except Exception:
            col = (150, 150, 150)

        # anonymize
        if anonymize:
            hy2 = min(frame.shape[0], y1 + (y2-y1)//3)
            roi = frame[max(0,y1):hy2, max(0,x1):min(frame.shape[1],x2)]
            if roi.size > 0:
                frame[max(0,y1):hy2, max(0,x1):min(frame.shape[1],x2)] = \
                    cv2.GaussianBlur(roi, (51,51), 0)

        if state.is_staff:
            for i in range(0, x2-x1, 10):
                cv2.line(frame,(x1+i,y1),(min(x1+i+5,x2),y1),col,2)
                cv2.line(frame,(x1+i,y2),(min(x1+i+5,x2),y2),col,2)
            for i in range(0, y2-y1, 10):
                cv2.line(frame,(x1,y1+i),(x1,min(y1+i+5,y2)),col,2)
                cv2.line(frame,(x2,y1+i),(x2,min(y1+i+5,y2)),col,2)
            label = f"Staff #{p['id']}"
        else:
            cv2.rectangle(frame,(x1,y1),(x2,y2),col,2)
            label = f"#{p['id']} {state.behavior_name}"

        (tw,th),_ = cv2.getTextSize(label,cv2.FONT_HERSHEY_SIMPLEX,0.5,2)
        cv2.rectangle(frame,(x1,y1-th-8),(x1+tw+6,y1),col,-1)
        cv2.putText(frame,label,(x1+3,y1-4),
                    cv2.FONT_HERSHEY_SIMPLEX,0.5,(10,10,10),2)

        if state.needs_staff and not state.is_staff:
            cv2.putText(frame,"! ASSIST",(x1,y2+18),
                        cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,50,255),2)

        for tx,ty in p["trajectory"][-20:]:
            cv2.circle(frame,(tx,ty),2,col,-1)

    return frame


def draw_hud(frame, cam_key, states) -> np.ndarray:
    n_staff   = sum(1 for s in states.values() if s.is_staff)
    n_cust    = sum(1 for s in states.values() if not s.is_staff)
    n_alert   = sum(1 for s in states.values() if s.needs_staff)
    hud = f"{cam_key}  customers:{n_cust}  staff:{n_staff}  alert:{n_alert}"
    cv2.putText(frame, hud, (10, frame.shape[0]-12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 2)
    return frame
