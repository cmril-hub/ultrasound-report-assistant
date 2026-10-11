# Ultrasound Report Assistant (Streamlit)

Upload the saved scan images for one patient. The app reads the scanner's on-screen
measurements and labels, drafts a report in the radiologist's own wording, lets the
radiologist review and edit it, and downloads it as PDF or Word. Drafts stay marked
DRAFT until the named radiologist ticks that they have reviewed them.

## Deploy on Streamlit Community Cloud
1. Put these files in a **private** GitHub repository (keep the folder layout,
   including `.streamlit/config.toml`).
2. Upload the `letterhead/` folder too.
3. At share.streamlit.io choose **Create app** and select the repository, branch
   and `streamlit_app.py`.
4. Before or after deploying, open **App settings > Secrets** and paste:
   `APP_PASSWORD = "choose-a-strong-password"`
   The app will not open without it.
5. In **Sharing**, keep the app restricted to people you invite if your plan allows.

`packages.txt` makes the server install Tesseract OCR; `requirements.txt` the Python packages.

## Run on your own computer
```
pip install -r requirements.txt
copy .streamlit\secrets.toml.example .streamlit\secrets.toml   (then edit the password)
streamlit run streamlit_app.py
```
Tesseract must be installed locally (Windows: https://github.com/UB-Mannheim/tesseract/wiki).

## Letterhead and patient table
Every PDF/Word report starts with the hospital letterhead (crest, hospital name, address,
"RADIOLOGY REPORT") and the patient table: Surname, Other Name (s), Age, Sex, Hospital No,
X-Ray/USS/CT No. The letterhead lives in the `letterhead/` folder:
- `letterhead.json` - hospital name, address and heading text
- `logo_left.png`, `logo_right.png` - the two logos. The current ones were cut from a
  screenshot and print slightly soft; replace them with the original image files
  (same names) for sharp printing.

## How age and sex are used
Age and Sex from the patient table drive the analysis:
- Sex decides whether the prostate or the uterus is reported (and flags images that don't match).
- Age: adult cut-offs (liver > 160 mm, spleen > 130 mm, prostate grading, kidney 80-130 mm check)
  apply from 16 years or "AD". Below 16 they are switched off and the conclusion is left for the
  radiologist to complete against age charts. Ages like 45, 45yrs, 6 months, 3/12, 2wks are understood.

## Patient data
Images are processed in a temporary folder for the session and are not saved by the app.
Never commit images or report files to the repository (`.gitignore` blocks them).
Past reports for the "similar reports" panel are uploaded per session from the sidebar.
