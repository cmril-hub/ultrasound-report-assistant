"""Draft an ultrasound report from one patient's images.

Pipeline
  1. read_image()      OCR the scanner overlay: preset, caliper values, typed labels
  2. assign_organs()   decide which organ each caliper value belongs to (labels, preset, layout)
  3. compose()         write the report in the radiologist's wording, grading values with the
                       thresholds learned from the archive (knowledge.py), plus any findings the
                       reader ticks
  4. similar_reports() nearest past reports from the archive, for reference
"""
FILES_VERSION = "2026-10-11"   # must match streamlit_app.py

import re, json, math
from pathlib import Path
import cv2, numpy as np, pytesseract

import knowledge as K

# ----------------------------------------------------------------------------- OCR
W, H = 1392, 944
HDR = (0, 90, 800, 1392)
MEAS_R = (48, 330, 1150, 1392)
MEAS_L = (48, 330, 560, 700)
MEAS_RE = re.compile(r"(?:([A-Za-z][A-Za-z0-9\-]*(?:[ \-][A-Za-z0-9\-]+)*)\s*[:;.]?\s*)?(-?\d+\.\d+)\s*(mm|cm3|cm/s|cm|ml|mL|%|bpm)\b")
NAME_BLOCK_WORDS = 2      # labels that look like a person's name are not used and are masked on display


def _prep(crop, scale=3):
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _, t = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return t


def _ocr(img, psm=6):
    return pytesseract.image_to_string(img, config=f"--psm {psm}")


def _label_mask(im):
    b, g, r = [im[:, :, i].astype(int) for i in range(3)]
    m = ((((r > 170) & (g > 170) & (b < 110)) | ((g > 150) & (r < 120) & (b < 120))) * 255).astype(np.uint8)
    m[:90] = 0
    m[:330, 1150:] = 0
    m = cv2.dilate(m, np.ones((2, 2), np.uint8))
    return 255 - cv2.resize(m, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)


def load_image(path):
    im = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if im is not None and im.shape[:2] != (H, W):
        im = cv2.resize(im, (W, H))
    return im


def read_image(path):
    im = load_image(path)
    if im is None:
        return None
    rec = {'file': Path(path).name, 'date': None, 'time': None, 'preset': '', 'measurements': [], 'labels': []}
    hdr = _ocr(_prep(im[HDR[0]:HDR[1], HDR[2]:HDR[3]]))
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2}:\d{2}:\d{2})", hdr)
    if m:
        rec['date'], rec['time'] = f"{m[3]}-{m[2]}-{m[1]}", m[4]
    m = re.search(r"\b([CLP]\d{3})\s+(.+?)\s+MI", hdr)
    if m:
        rec['probe'], rec['preset'] = m[1], m[2].strip()
    for y0, y1, x0, x1 in (MEAS_R, MEAS_L):
        for line in _ocr(_prep(im[y0:y1, x0:x1])).splitlines():
            for mm in MEAS_RE.finditer(line.replace(',', '.')):
                rec['measurements'].append({'label': re.sub(r"^[\d\W_]+", "", mm[1] or '').strip(),
                                            'value': float(mm[2]), 'unit': mm[3] or ''})
    rec['labels'] = [w.upper() for w in re.findall(r"[A-Za-z][A-Za-z\-]{1,}", _ocr(_label_mask(im), psm=11))]
    return rec


def masked_preview(path, out_path, max_w=700):
    """Image for display with the typed patient-name area blacked out (bottom label band)."""
    im = load_image(path)
    b, g, r = [im[:, :, i].astype(int) for i in range(3)]
    yellow = (r > 170) & (g > 170) & (b < 110)
    # names are typed in yellow capitals near the bottom of a pane; black out wide yellow text runs
    rows = np.where(yellow[300:].sum(axis=1) > 25)[0] + 300
    for y in rows:
        xs = np.where(yellow[y])[0]
        if xs.size and xs.max() - xs.min() > 120:
            im[max(0, y - 14):y + 14, max(0, xs.min() - 6):xs.max() + 6] = 0
    scale = max_w / im.shape[1]
    im = cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(out_path), im, [cv2.IMWRITE_JPEG_QUALITY, 85])


# ------------------------------------------------------------------ organ assignment
ORGANS = ['kidney_r', 'kidney_l', 'liver', 'spleen', 'prostate', 'pvr', 'uterus', 'fibroid', 'breast_lesion', 'axillary_node', 'ignore']
ORGAN_NAMES = {'kidney_r': 'Right kidney length (mm)', 'kidney_l': 'Left kidney length (mm)',
               'liver': 'Liver span (mm)', 'spleen': 'Spleen span (mm)', 'prostate': 'Prostate volume (cm3)',
               'pvr': 'Post-void residual (ml)', 'uterus': 'Uterus AP (mm)', 'fibroid': 'Fibroid dimension (mm)', 'breast_lesion': 'Breast lesion dimension (mm)', 'axillary_node': 'Axillary node (mm)',
               'ignore': 'Not used'}


def _has(labels, *keys):
    s = ' '.join(labels)
    return any(k in s for k in keys)


def _ellipsoid_ml(d):
    return d[0] * d[1] * d[2] * 0.523 / 1000 if len(d) >= 3 else None


def assign_organs(recs):
    """Return list of {file, organ, value, source} items, one per useful caliper value."""
    items = []
    for r in recs:
        L, P = r['labels'], (r.get('preset') or '').lower()
        ms = r['measurements']
        if not ms:
            continue
        Ds = [m['value'] for m in ms if m['unit'] in ('mm', '') and not m['label'].upper().startswith('V')]
        V = next((m['value'] for m in ms if m['unit'] == 'cm3' or m['label'].upper().endswith('V')), None)
        add = lambda organ, v, why: items.append({'file': r['file'], 'organ': organ, 'value': round(v, 2), 'source': why})
        named = False
        kid_seen = 0
        for m in ms:                                        # scanner-named measurements, e.g. Rt-Kidney-L
            lab = m['label'].upper()
            if 'IDNEY' in lab or 'KID' in lab:
                side = 'kidney_l' if lab.startswith('LT') or 'LT-' in lab else 'kidney_r' if lab.startswith('RT') or 'RT-' in lab else ('kidney_r', 'kidney_l')[min(kid_seen, 1)]
                kid_seen += 1; add(side, m['value'], f"labelled {m['label']}"); named = True
            elif 'LIVER' in lab:
                add('liver', m['value'], f"labelled {m['label']}"); named = True
            elif 'SPLEEN' in lab or 'PLEEN' in lab:
                add('spleen', m['value'], f"labelled {m['label']}"); named = True
        if named:
            continue
        if 'breast' in P or _has(L, 'AXILLA', 'BREAST'):
            for d in Ds:
                add('axillary_node' if d < 15 else 'ignore', d, 'breast image')
            continue
        if _has(L, 'PVR'):
            add('pvr', V if V is not None else _ellipsoid_ml(Ds) or 0, 'image labelled PVR')
            continue
        if V is not None and (_has(L, 'PROSTATE') or P in ('kidney', 'uro', 'abd')):
            add('prostate', V, 'volume on image labelled PROSTATE' if _has(L, 'PROSTATE') else 'volume measurement')
            continue
        kid_r = _has(L, 'RT-KID', 'RT KID', 'RKD', 'RT-KIDNEY', 'RT') and _has(L, 'KID', 'RKD')
        kid_l = _has(L, 'LT-KID', 'LT KID', 'LKD', 'LT-KIDNEY', 'LT') and _has(L, 'KID', 'LKD')
        if kid_r and kid_l:
            if len(Ds) >= 4:
                add('kidney_r', max(Ds[0], Ds[1]), 'dual kidney image, values 1-2'); add('kidney_l', max(Ds[2], Ds[3]), 'dual kidney image, values 3-4')
            elif len(Ds) == 3:
                add('kidney_r', max(Ds[0], Ds[1]), 'dual kidney image, values 1-2'); add('kidney_l', Ds[2], 'dual kidney image, value 3')
            elif len(Ds) == 2 and min(Ds) > 0.6 * max(Ds):
                add('kidney_r', Ds[0], 'dual kidney image'); add('kidney_l', Ds[1], 'dual kidney image')
            else:
                for d in Ds:
                    items.append({'file': r['file'], 'organ': None, 'value': round(d, 2), 'source': 'kidney image, side unclear'})
            continue
        if _has(L, 'LIVER') and _has(L, 'SPLEEN') and len(Ds) >= 2:
            add('liver', Ds[0], 'liver/spleen dual image'); add('spleen', Ds[1], 'liver/spleen dual image'); continue
        if (kid_r or kid_l) and Ds:
            add('kidney_r' if kid_r else 'kidney_l', max(Ds), 'single kidney image'); continue
        if _has(L, 'LIVER') and Ds:
            add('liver', max(Ds), 'image labelled Liver'); continue
        if _has(L, 'SPLEEN') and Ds:
            add('spleen', max(Ds), 'image labelled Spleen'); continue
        if _has(L, 'UTERUS', 'UT') and Ds:
            add('uterus', Ds[0], 'image labelled Uterus'); continue
        for d in Ds:
            items.append({'file': r['file'], 'organ': None, 'value': round(d, 2), 'source': 'no organ label on image'})
    return items


def dedupe(items):
    """Drop repeats of the same value for the same organ (screenshots saved twice)."""
    seen, out = set(), []
    for it in items:
        k = (it['organ'], it['value'])
        if k in seen:
            continue
        seen.add(k); out.append(it)
    return out


def warnings(items, ctx):
    w = []
    by = {}
    for it in items:
        if it['organ'] in ('prostate', 'pvr'):
            by.setdefault(it['organ'], set()).add(it['value'])
    for o, vs in by.items():
        if len(vs) > 1:
            w.append(f"{ORGAN_NAMES[o]}: different values on different images ({', '.join(map(str, sorted(vs)))}). "
                     "Are these images from one patient? The last value is used; change or set the others to 'Not used'.")
    for it in items:
        if it['organ'] in ('kidney_r', 'kidney_l') and it['value'] < 70:
            w.append(f"{ORGAN_NAMES[it['organ']]} {it['value']} mm is short for a kidney length; it may be a width.")
        if it['organ'] == 'uterus' and it['value'] > 60:
            w.append(f"Uterus {it['value']} mm: check whether this is length or AP dimension, and whether the uterus is bulky.")
    unl = [it for it in items if not it['organ']]
    if unl:
        w.append(f"{len(unl)} measurement(s) have no organ label on the image. Assign them below if they belong in the report.")
    if ctx['sex'] == 'unknown' and ctx['exam'] == 'abdomen':
        w.append("Sex is not given in the patient table and could not be inferred from the images. Enter it.")
    organs = {it['organ'] for it in items}
    if ctx['sex'] == 'female' and 'prostate' in organs:
        w.append("Patient table says Female but a prostate volume was read from the images - check the patient and images match.")
    if ctx['sex'] == 'male' and organs & {'uterus', 'fibroid'}:
        w.append("Patient table says Male but uterus measurements were read from the images - check the patient and images match.")
    age = ctx.get('age') or {}
    if age.get('adult') is False:
        w.append(f"Paediatric patient (age {age.get('text')}): adult cut-offs are switched off; judge sizes against age charts.")
    if age.get('adult') and ctx['exam'] == 'abdomen':
        lo, hi = K.ADULT_KIDNEY_MM
        for it in items:
            if it['organ'] in ('kidney_r', 'kidney_l') and it['value'] >= 70 and not lo <= it['value'] <= hi:
                w.append(f"{ORGAN_NAMES[it['organ']]} {it['value']} mm is outside the usual adult range ({lo}-{hi} mm).")
    return w


def infer_context(recs, items):
    presets = [(r.get('preset') or '').lower() for r in recs]
    labels = [l for r in recs for l in r['labels']]
    breast = sum('breast' in p for p in presets)
    exam = 'breast' if breast and breast >= len(recs) / 2 else 'abdomen'
    organs = {i['organ'] for i in items}
    if 'prostate' in organs or _has(labels, 'PROSTATE'):
        sex = 'male'
    elif 'uterus' in organs or _has(labels, 'UTERUS', 'OVARY') or any(p in ('gyn', '1st trim', '2nd/3rd trim') for p in presets):
        sex = 'female'
    else:
        sex = 'unknown'
    dates = sorted({r['date'] for r in recs if r.get('date')})
    return {'exam': exam, 'sex': sex, 'date': dates[0] if dates else None}


def collect(items):
    """organ -> value (largest kidney/liver/spleen length, last volume)."""
    v = {}
    for it in items:
        o = it['organ']
        if not o or o == 'ignore':
            continue
        if o in ('axillary_node', 'fibroid', 'breast_lesion'):
            v.setdefault(o, []).append(it['value'])
        elif o in ('kidney_r', 'kidney_l', 'liver', 'spleen', 'uterus'):
            v[o] = max(v.get(o, 0), it['value'])
        else:
            v[o] = it['value']
    return v


# ------------------------------------------------------------- patient details
def parse_age(text):
    """'45', '45yrs', '6 months', '3/12', '2wks', 'AD' (adult) -> {'years': float|None, 'adult': bool|None}."""
    t = (text or '').strip().lower()
    if not t:
        return {'years': None, 'adult': None, 'text': ''}
    if t in ('ad', 'adult', 'a'):
        return {'years': None, 'adult': True, 'text': text}
    m = re.match(r'(\d+(?:\.\d+)?)\s*/\s*12', t)            # 3/12 = 3 months
    if m:
        y = float(m[1]) / 12
    else:
        m = re.match(r'(\d+(?:\.\d+)?)\s*([a-z]*)', t)
        if not m:
            return {'years': None, 'adult': None, 'text': text}
        n, unit = float(m[1]), m[2]
        y = n / 12 if unit.startswith('m') else n / 52 if unit.startswith('w') else n / 365 if unit.startswith('d') else n
    return {'years': round(y, 2), 'adult': y >= K.PAEDIATRIC_BELOW_YEARS, 'text': text}


def patient_sex(table_sex, inferred):
    t = (table_sex or '').strip().lower()
    if t.startswith('m'):
        return 'male'
    if t.startswith('f'):
        return 'female'
    return inferred


# ------------------------------------------------------------------------ compose
def _grade(vol):
    for lim, g in K.PROSTATE_GRADES:
        if vol <= lim:
            return g


def compose(values, ctx, findings=(), indication=''):
    """Return {'title','indication','paragraphs':[...],'conclusion':[...],'advice':[...],'basis':[...]}"""
    f = {k: K.FINDINGS[k] for k in findings if k in K.FINDINGS}
    replaced = {x['replaces'] for x in f.values() if x['replaces']}
    paras, concl, advice, basis = [], [], [], []
    age = ctx.get('age') or {}
    child = age.get('adult') is False
    if child:
        basis.append(f"Paediatric patient (age {age.get('text')}): adult size cut-offs for liver, spleen and prostate "
                     "were NOT applied - compare the measurements with age-appropriate charts.")
    elif age.get('adult'):
        basis.append(f"Adult patient (age {age.get('text')}): adult reference cut-offs applied.")
    else:
        basis.append("Age not given: adult reference cut-offs assumed.")
    kr, kl = values.get('kidney_r'), values.get('kidney_l')
    size = (K.KIDNEYS_SIZE.format(r=kr, l=kl) if kr and kl else
            K.KIDNEY_ONE_SIZE.format(side='right', v=kr) if kr else
            K.KIDNEY_ONE_SIZE.format(side='left', v=kl) if kl else '')
    liver = values.get('liver')
    fmt = {'size': size,
           'span_c': f", with a cranio-caudal span of about {liver:.2f}mm." if liver else ".",
           'span_m': f", measuring about {liver:.2f}mm in cranio-caudal span," if liver else "",
           'fib_size': (' It measured ' + ' x '.join(f'{x:.2f}' for x in values['fibroid'][:3]) + 'mm in size.') if values.get('fibroid') else '',
           'lesion_size': (' It measured ' + ' x '.join(f'{x:.2f}' for x in values['breast_lesion'][:2]) + 'mm in size.') if values.get('breast_lesion') else '',
           'ap_c': f" It measured {values['uterus']:.2f}mm in its maximum AP dimension." if values.get('uterus') else ""}

    if ctx['exam'] == 'breast':
        nodes = values.get('axillary_node', [])
        paras += [K.BREAST_DENSITY]
        paras += [f['fibroadenoma']['text'].format(**fmt)] if 'fibroadenoma' in f else [K.BREAST_NO_MASS]
        paras += [K.BREAST_NIPPLE]
        if nodes:
            avg = sum(nodes) / len(nodes)
            paras.append(K.BREAST_NODES.format(v=avg))
            basis.append(f"Axillary nodes {', '.join(f'{n:.2f}' for n in nodes)} mm, average {avg:.2f} mm")
        concl += [f['fibroadenoma']['conclusion']] if 'fibroadenoma' in f else [K.CONCL_NORMAL_BREAST]
        return {'title': K.TITLES['breast'], 'indication': indication or K.BREAST_INDICATION,
                'paragraphs': paras, 'conclusion': concl, 'advice': advice, 'basis': basis}

    # liver
    if 'liver' in replaced:
        key = next(k for k, x in f.items() if x['replaces'] == 'liver')
        paras.append(f[key]['text'].format(**fmt))
    elif liver and liver > K.LIVER_ENLARGED_MM and not child:
        paras.append(K.LIVER_ENLARGED.format(v=liver)); concl.append(K.CONCL_HEPATOMEGALY)
        basis.append(f"Liver span {liver:.2f} mm > {K.LIVER_ENLARGED_MM} mm -> hepatomegaly")
    else:
        paras.append(K.LIVER_NORMAL.format(span=K.LIVER_SPAN.format(v=liver) if liver else ''))
        if liver: basis.append(f"Liver span {liver:.2f} mm " + ("(adult cut-off not applied)" if child else f"(normal <= {K.LIVER_ENLARGED_MM})"))
    # gall bladder
    if 'gallbladder' in replaced:
        paras.append(f['cholelithiasis']['text'])
    else:
        paras.append(K.GALLBLADDER_NORMAL)
    # kidneys
    if 'kidneys' in replaced:
        key = next(k for k, x in f.items() if x['replaces'] == 'kidneys')
        paras.append(f[key]['text'].format(**fmt))
    else:
        paras.append(K.KIDNEYS_NORMAL.format(size=size))
    for k in ('renal_cyst_left', 'renal_cyst_right'):
        if k in f:
            paras.append(f[k]['text'])
    if kr or kl:
        lo, hi = K.ADULT_KIDNEY_MM
        out = [f"{s} {v:.2f} mm" for s, v in (('right', kr), ('left', kl)) if v and not child and not lo <= v <= hi]
        basis.append(f"Kidney lengths R {kr or '-'} / L {kl or '-'} mm" +
                     (f" - outside usual adult range {lo}-{hi} mm ({', '.join(out)}): check" if out else
                      "" if child else f" (usual adult range {lo}-{hi} mm)"))
    # spleen, pancreas
    spl = values.get('spleen')
    if spl and spl > K.SPLEEN_ENLARGED_MM and not child:
        paras.append(K.SPLEEN_ENLARGED.format(v=spl)); concl.append(K.CONCL_SPLENOMEGALY)
        basis.append(f"Spleen {spl:.2f} mm > {K.SPLEEN_ENLARGED_MM} mm -> splenomegaly")
    else:
        paras.append(K.SPLEEN_PARA.format(spl=f" ({spl:.2f}mm)" if spl else ''))
    paras.append(K.BOWEL)
    # bladder, PVR
    pvr = values.get('pvr')
    pvr_sig = pvr is not None and pvr > K.PVR_SIGNIFICANT_ML
    if pvr is not None:
        basis.append(f"PVR {pvr:.2f} ml ({'significant' if pvr_sig else 'not significant'}; cut-off {K.PVR_SIGNIFICANT_ML} ml)")
    pvr_txt = '' if pvr is None else (K.PVR_SIG if pvr_sig else K.PVR_NIL).format(v=pvr)
    paras.append(K.BLADDER.format(pvr=pvr_txt))
    # prostate / uterus
    if ctx['sex'] == 'male':
        vol = values.get('prostate')
        g = _grade(vol) if vol and not child else None
        if vol: basis.append(f"Prostate {vol:.2f} cm3 " + ("(adult grading not applied)" if child else f"-> {g or 'normal'} (normal <= 30, mild <= 50, moderate <= 80)"))
        if g:
            paras.append(K.PROSTATE_ENLARGED.format(grade=g if g != 'severe' else 'marked', v=vol))
            concl.append(K.CONCL_PROSTATE.format(Grade=g.capitalize(), pvr=K.CONCL_PVR if pvr_sig else ''))
            advice.append(K.ADVICE_PSA)
        else:
            paras.append(K.PROSTATE_NORMAL.format(v=vol) if vol else K.PROSTATE_NORMAL_NOVOL)
    elif ctx['sex'] == 'female':
        if 'uterus' in replaced:
            paras.append(f['fibroid']['text'].format(**fmt))
        else:
            ut = values.get('uterus')
            paras.append(K.UTERUS_NORMAL.format(ap=K.UTERUS_AP.format(v=ut) if ut else ''))
    for k, x in f.items():
        if x['conclusion'] not in concl:
            concl.append(x['conclusion'])
    if not concl:
        concl = [K.CONCL_PAEDIATRIC_REVIEW] if child else [K.CONCL_NORMAL]
    return {'title': K.TITLES['abdomen'], 'indication': indication, 'paragraphs': paras,
            'conclusion': concl, 'advice': advice, 'basis': basis}


# ----------------------------------------------------------------- report archive
DATE = re.compile(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})\b")


def parse_archive(folder):
    """Split every .docx in folder into individual reports (same rules as the matching notebook)."""
    import docx
    out, seen = [], set()
    for p in sorted(Path(folder).rglob('*.docx')):
        if p.name.startswith('~$'):
            continue
        buf = []
        for t in (x.text.strip() for x in docx.Document(str(p)).paragraphs):
            if not t or re.fullmatch(r"(Consultant\s+)?Radiologist\.?", t, re.I):
                continue
            m = DATE.search(t)
            is_sig = m and (re.search(r"Dr\.?\s", t, re.I) or len(DATE.sub('', t).strip()) < 4)
            if is_sig and buf:
                body = '\n'.join(buf)
                if (m[0], body) not in seen:
                    seen.add((m[0], body))
                    c = re.search(r"Conclusion\s*:?(.*)", body, re.I | re.S)
                    out.append({'file': p.name, 'date': m[0], 'text': body, 'conclusion': c[1].strip() if c else ''})
                buf = []
            elif not is_sig:
                buf.append(t)
    return out


class Archive:
    def __init__(self, reports):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.reports = reports
        self.vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words='english',
                                   token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-]+\b")
        self.X = self.vec.fit_transform([r['text'] for r in reports]) if reports else None

    def similar(self, text, k=3):
        if self.X is None:
            return []
        from sklearn.metrics.pairwise import linear_kernel
        s = linear_kernel(self.vec.transform([text]), self.X).ravel()
        idx = s.argsort()[::-1][:k]
        return [{**self.reports[i], 'score': round(float(s[i]), 2)} for i in idx]


def report_text(rep):
    lines = [rep['title']]
    if rep.get('indication'):
        lines.append('INDICATION: ' + rep['indication'])
    lines += rep['paragraphs']
    lines.append('Conclusion: ' + ' '.join(rep['conclusion']))
    lines += rep['advice']
    return '\n'.join(lines)
