"""Ultrasound Report Assistant - Streamlit version (password protected).

Upload one patient's scan images -> the scanner's on-screen measurements are read (OCR) ->
a draft report is written in the radiologist's wording -> review, edit, download PDF / Word.

Password: set APP_PASSWORD in the app's Secrets (Streamlit Cloud: App settings > Secrets).
The app refuses to run without one.
"""
import os, io, re, hmac, shutil, tempfile, datetime as dt, hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

import engine
import render
import knowledge as K

st.set_page_config(page_title="Ultrasound Report Assistant", page_icon="🩺", layout="wide")

# ---- all files must come from the same version (a common slip when updating GitHub one file at a time)
FILES_VERSION = "2026-10-11"
_stale = [name for name, mod in (("engine.py", engine), ("knowledge.py", K), ("render.py", render))
          if getattr(mod, "FILES_VERSION", None) != FILES_VERSION]
if _stale or not (Path(__file__).parent / "letterhead" / "letterhead.json").exists():
    st.error("Some app files on GitHub are out of date, so the app can't start.\n\n"
             "Upload the latest copies of: **" + ", ".join(_stale + ([] if (Path(__file__).parent / "letterhead" / "letterhead.json").exists() else ["letterhead/ folder"])) +
             "** from the newest zip (replace the old ones), then reload this page.")
    st.stop()


# =========================================================================== password
def _configured_password():
    try:
        pw = st.secrets.get("APP_PASSWORD", "")
    except Exception:          # no secrets file at all
        pw = ""
    return pw or os.environ.get("APP_PASSWORD", "")


def password_gate():
    pw = _configured_password()
    if not pw:
        st.error("This app has no password set, so it will not open.\n\n"
                 "On Streamlit Cloud: **App settings → Secrets** and add a line\n\n"
                 "`APP_PASSWORD = \"choose-a-strong-password\"`\n\n"
                 "Running locally: create `.streamlit/secrets.toml` with the same line.")
        st.stop()
    if st.session_state.get("auth_ok"):
        return
    st.title("Ultrasound Report Assistant")
    st.caption("Restricted to clinic staff.")
    with st.form("login"):
        entered = st.text_input("Password", type="password")
        if st.form_submit_button("Enter"):
            if hmac.compare_digest(entered.encode(), pw.encode()):
                st.session_state.auth_ok = True
                st.rerun()
            else:
                st.error("Wrong password.")
    st.stop()


password_gate()

# ============================================================================== state
ss = st.session_state
ss.setdefault("case", None)              # dict with recs/items/ctx/tmpdir/files
ss.setdefault("archive", None)
ss.setdefault("rad_name", "")
ss.setdefault("rad_title", "Consultant Radiologist")
ORG_LABEL = {o: engine.ORGAN_NAMES[o] for o in engine.ORGANS}
LABEL_ORG = {v: k for k, v in ORG_LABEL.items()}
UNASSIGNED = "— unassigned —"
PT_FIELDS = [("surname", "pt_surname"), ("other_names", "pt_other"), ("age", "pt_age"), ("sex_t", "pt_sex"),
             ("hospital_no", "pt_hosp"), ("study_no", "pt_study"), ("referrer", "pt_ref")]


def patient_ctx(case):
    """Age and sex for the analysis come from the patient table (sex falls back to what the images suggest)."""
    return {"exam": case["exam"], "sex": engine.patient_sex(ss.get("pt_sex", ""), case["sex_inferred"]),
            "age": engine.parse_age(ss.get("pt_age", ""))}


def fmt_date(iso):
    try:
        return dt.date.fromisoformat(str(iso)).strftime("%d/%m/%Y")
    except Exception:
        return dt.date.today().strftime("%d/%m/%Y")


def new_case_from_uploads(files, meta):
    """Save uploads to a private temp folder, OCR them, build the first draft."""
    old = ss.case
    if old and old.get("tmpdir"):
        shutil.rmtree(old["tmpdir"], ignore_errors=True)
    tmp = Path(tempfile.mkdtemp(prefix="usr_"))
    (tmp / "view").mkdir()
    recs, names = [], []
    bar = st.progress(0.0, text="Reading images…")
    for i, f in enumerate(files, 1):
        name = re.sub(r"[^A-Za-z0-9_.\-]", "_", Path(f.name).name)
        p = tmp / name
        p.write_bytes(f.getvalue())
        r = engine.read_image(p)
        if r:
            recs.append(r); names.append(name)
            engine.masked_preview(p, tmp / "view" / (Path(name).stem + ".jpg"))
        bar.progress(i / len(files), text=f"Reading images… {i}/{len(files)}")
    bar.empty()
    items = engine.dedupe(engine.assign_organs(recs))
    ctx = engine.infer_context(recs, items)
    case = {"id": hashlib.md5("".join(names).encode()).hexdigest()[:8] + dt.datetime.now().strftime("%H%M%S"),
            "tmpdir": str(tmp), "files": names, "recs": recs, "items": items,
            "exam": ctx["exam"], "sex_inferred": ctx["sex"], "date": ctx["date"] or dt.date.today().isoformat(),
            "findings": [], "ver": 0, "indication": meta.get("indication", "")}
    ss.case = case
    for k, key in PT_FIELDS:
        ss[key] = meta.get(k, "")
    write_draft_to_editor(case)


def write_draft_to_editor(case):
    rep = engine.compose(engine.collect(case["items"]), patient_ctx(case), case["findings"], case.get("indication", ""))
    ss.ed_title = rep["title"]
    ss.ed_body = "\n\n".join(rep["paragraphs"])
    ss.ed_concl = "\n".join(rep["conclusion"])
    ss.ed_advice = "\n".join(rep["advice"])
    ss.ed_indication = rep.get("indication") or ""
    ss.ed_basis = rep["basis"]
    ss.approved = False


def items_from_editor(df):
    out = []
    for _, row in df.iterrows():
        try:
            v = float(row["Value"])
        except (TypeError, ValueError):
            continue
        if pd.isna(v):
            continue
        v = round(v, 2)
        org = LABEL_ORG.get(row["Organ"]) if row["Organ"] != UNASSIGNED else None
        out.append({"file": row["Image"] if isinstance(row["Image"], str) else "added by hand", "organ": org,
                    "value": v, "source": row["Why"] if isinstance(row["Why"], str) else "entered by reader"})
    return out


def current_report():
    case = ss.case
    return {
        "title": ss.get("ed_title", ""), "indication": ss.get("ed_indication", ""),
        "paragraphs": [p.strip() for p in re.split(r"\n\s*\n", ss.get("ed_body", "")) if p.strip()],
        "conclusion": [l.strip() for l in ss.get("ed_concl", "").splitlines() if l.strip()] or [K.CONCL_NORMAL],
        "advice": [l.strip() for l in ss.get("ed_advice", "").splitlines() if l.strip()],
        "approved": bool(ss.get("approved")) and bool(ss.rad_name.strip()),
        "exam": case["exam"], "date_str": fmt_date(case["date"]),
        "radiologist": ss.rad_name.strip(), "radiologist_title": ss.rad_title.strip(),
        "surname": ss.get("pt_surname", ""), "other_names": ss.get("pt_other", ""), "age": ss.get("pt_age", ""),
        "sex_label": ss.get("pt_sex") or {"male": "M", "female": "F"}.get(patient_ctx(case)["sex"], ""),
        "hospital_no": ss.get("pt_hosp", ""), "study_no": ss.get("pt_study", ""), "referrer": ss.get("pt_ref", ""),
    }


# ============================================================================ sidebar
with st.sidebar:
    st.header("Reporting radiologist")
    st.text_input("Name (printed on the report)", key="rad_name", placeholder="e.g. Dr. A. Bello")
    st.text_input("Title", key="rad_title")
    st.divider()
    st.subheader("Past reports (optional)")
    st.caption("Upload the radiologist's .docx report files to show similar past reports beside each draft. "
               "They are kept only for this session.")
    arch_files = st.file_uploader("Report archives (.docx)", type=["docx"], accept_multiple_files=True,
                                  key="arch_up", label_visibility="collapsed")
    if arch_files:
        sig = tuple(sorted((f.name, f.size) for f in arch_files))
        if ss.get("arch_sig") != sig:
            with st.spinner("Reading past reports…"):
                d = Path(tempfile.mkdtemp(prefix="arch_"))
                for f in arch_files:
                    (d / re.sub(r"[^A-Za-z0-9_.\-]", "_", f.name)).write_bytes(f.getvalue())
                ss.archive = engine.Archive(engine.parse_archive(d))
                shutil.rmtree(d, ignore_errors=True)
                ss.arch_sig = sig
        st.success(f"{len(ss.archive.reports)} past reports loaded")
    st.divider()
    if st.button("Log out"):
        for k in list(ss.keys()):
            del ss[k]
        st.rerun()

# ============================================================================== header
st.title("Ultrasound Report Assistant")
st.caption("Prototype · drafts must be reviewed and signed by the radiologist · "
           "images are processed for this session only and typed patient names are blacked out on screen")

# ========================================================================= new report
with st.expander("New report", expanded=ss.case is None):
    with st.form("new_case", clear_on_submit=False):
        files = st.file_uploader("Scan images for ONE patient (.jpg)", type=["jpg", "jpeg", "png", "bmp"],
                                 accept_multiple_files=True)
        st.markdown("**Patient details** (printed in the table under the letterhead)")
        c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
        surname = c1.text_input("Surname")
        other_names = c2.text_input("Other Name (s)")
        age = c3.text_input("Age", placeholder="45 / 6 months / AD")
        sex_t = c4.selectbox("Sex", ["", "M", "F"])
        c5, c6 = st.columns(2)
        hospital_no = c5.text_input("Hospital No")
        study_no = c6.text_input("X-Ray/USS/CT No")
        c7, c8 = st.columns(2)
        referrer = c7.text_input("Referred by")
        indication = c8.text_input("Indication", placeholder="e.g. Left breast lump")
        go = st.form_submit_button("Read images and draft report", type="primary")
    if go:
        if not files:
            st.warning("Choose the patient's images first.")
        elif not ss.rad_name.strip():
            st.warning("Enter the reporting radiologist's name in the left sidebar first.")
        else:
            new_case_from_uploads(files, {"surname": surname.strip(), "other_names": other_names.strip(),
                                          "age": age.strip(), "sex_t": sex_t, "hospital_no": hospital_no.strip(),
                                          "study_no": study_no.strip(), "referrer": referrer.strip(),
                                          "indication": indication.strip()})

case = ss.case
if not case:
    st.info("Enter your name in the sidebar, then upload one patient's images above.")
    st.stop()

# ============================================================================ the case
left, right = st.columns([1, 1.05], gap="large")

with left:
    who = " ".join(x for x in (ss.get("pt_surname", ""), ss.get("pt_other", "")) if x) or "Unnamed patient"
    st.subheader(f"{who} · scan {fmt_date(case['date'])} · {len(case['files'])} images")
    with st.expander("Patient details (letterhead table)", expanded=True):
        p1, p2, p3, p4 = st.columns([2, 2, 1, 1])
        p1.text_input("Surname", key="pt_surname")
        p2.text_input("Other Name (s)", key="pt_other")
        p3.text_input("Age", key="pt_age", help="e.g. 45, 45yrs, 6 months, 3/12, AD. Under 16: adult cut-offs are switched off.")
        p4.selectbox("Sex", ["", "M", "F"], key="pt_sex")
        p5, p6, p7 = st.columns(3)
        p5.text_input("Hospital No", key="pt_hosp")
        p6.text_input("X-Ray/USS/CT No", key="pt_study")
        p7.text_input("Referred by", key="pt_ref")
        pc = patient_ctx(case)
        a = pc["age"]
        st.caption("Analysis uses: sex **" + pc["sex"] + "**" + ("" if ss.get("pt_sex") else " (inferred from images)") +
                   " · age **" + (a["text"] or "not given") + "** → " +
                   ("paediatric – adult cut-offs off" if a["adult"] is False else "adult cut-offs") +
                   ". Press *Update draft* after changing these.")

    # images
    with st.expander("Images", expanded=True):
        cols = st.columns(3)
        by_img = {}
        for it in case["items"]:
            by_img.setdefault(it["file"], []).append(it)
        for i, (name, r) in enumerate(zip(case["files"], case["recs"])):
            chips = ", ".join(f"{ORG_LABEL.get(it['organ'], 'unassigned')}: {it['value']}"
                              for it in by_img.get(r["file"], [])) or "no measurements"
            cols[i % 3].image(str(Path(case["tmpdir"]) / "view" / (Path(name).stem + ".jpg")),
                              caption=f"{r.get('preset') or '—'} {r.get('time') or ''} · {chips}",
                              use_container_width=True)

    # measurements
    st.markdown("**Measurements read from the screen** — check each went to the right organ.")
    df = pd.DataFrame([{"Image": it["file"], "Value": it["value"],
                        "Organ": ORG_LABEL.get(it["organ"], UNASSIGNED), "Why": it["source"]}
                       for it in case["items"]], columns=["Image", "Value", "Organ", "Why"])
    edited = st.data_editor(
        df, key=f"ed_{case['id']}_{case['ver']}", hide_index=True, use_container_width=True, num_rows="dynamic",
        column_config={
            "Image": st.column_config.TextColumn(disabled=True),
            "Value": st.column_config.NumberColumn(format="%.2f", step=0.01),
            "Organ": st.column_config.SelectboxColumn(options=[UNASSIGNED] + list(ORG_LABEL.values()), required=True),
            "Why": st.column_config.TextColumn(disabled=True),
        })
    live_items = items_from_editor(edited)

    c1, c3 = st.columns(2)
    exam = c1.selectbox("Exam", ["abdomen", "breast"], index=["abdomen", "breast"].index(case["exam"]),
                        format_func=lambda x: {"abdomen": "Abdominopelvic", "breast": "Breast"}[x])
    sdate = c3.date_input("Scan date", value=dt.date.fromisoformat(case["date"]), format="DD/MM/YYYY")
    case["exam"] = exam

    for w in engine.warnings(live_items, patient_ctx(case)):
        st.warning(w)

    avail = {k: v["label"] for k, v in K.FINDINGS.items() if v["exam"] == exam}
    findings = st.multiselect("Findings seen on the images (inserts the radiologist's usual wording)",
                              options=list(avail), default=[f for f in case["findings"] if f in avail],
                              format_func=lambda k: avail[k])

    if st.button("Update draft from measurements", type="primary",
                 help="Rewrites the report on the right from the table and findings (replaces text edits)."):
        case.update({"items": live_items, "exam": exam, "date": sdate.isoformat(), "findings": findings,
                     "ver": case["ver"] + 1})
        write_draft_to_editor(case)
    else:
        case.update({"exam": exam, "date": sdate.isoformat()})

    if ss.get("ed_basis"):
        with st.expander("How the draft was decided"):
            for b in ss.ed_basis:
                st.write("• " + b)

with right:
    rep_ok = bool(ss.get("approved")) and bool(ss.rad_name.strip())
    if not rep_ok:
        st.markdown("<div style='color:#b01e1e;font-weight:700;text-align:center'>DRAFT – not yet reviewed and signed</div>",
                    unsafe_allow_html=True)
    st.text_input("Title", key="ed_title")
    if exam == "breast" or ss.get("ed_indication"):
        st.text_input("Indication", key="ed_indication")
    st.text_area("Findings (blank line between paragraphs)", key="ed_body", height=380)
    st.text_area("Conclusion (one item per line)", key="ed_concl", height=90)
    st.text_area("NB / advice (one per line)", key="ed_advice", height=70)
    st.markdown(f"<div style='display:flex;justify-content:space-between;font-family:Times New Roman,serif'>"
                f"<span>{fmt_date(case['date'])}</span><span style='text-align:right'>"
                f"{ss.rad_name or '<i>(radiologist name in sidebar)</i>'}<br>{ss.rad_title}</span></div>",
                unsafe_allow_html=True)
    st.checkbox(f"I, {ss.rad_name or '(enter your name in the sidebar)'}, have reviewed this report against "
                "the images — remove the DRAFT marking", key="approved", disabled=not ss.rad_name.strip())

    r = current_report()
    base = re.sub(r"[^A-Za-z0-9]+", "_", " ".join([ss.get("pt_surname", ""), ss.get("pt_hosp", "")]).strip() or "report").strip("_") + "_" + case["date"]
    if not r["approved"]:
        base += "_DRAFT"
    d1, d2 = st.columns(2)
    d1.download_button("Download PDF", render.to_pdf(r), file_name=base + ".pdf", mime="application/pdf",
                       use_container_width=True, type="primary")
    d2.download_button("Download Word (.docx)", render.to_docx(r), file_name=base + ".docx",
                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                       use_container_width=True)

    if ss.archive and ss.archive.reports:
        st.markdown("**Similar past reports**")
        for s in ss.archive.similar(engine.report_text({**r, "paragraphs": r["paragraphs"]}), k=3):
            with st.expander(f"{s['date']} · {s['conclusion'][:90]}"):
                st.text(s["text"])
