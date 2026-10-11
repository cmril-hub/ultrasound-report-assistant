"""Wording and grading rules taken from the radiologist's own report archive.

Every sentence below is the radiologist's most frequent phrasing for that organ/finding
(numbers replaced by placeholders). Thresholds were read off the archive:
  prostate volume  normal <= 30 cm3, mild 30-50, moderate 50-80, severe > 80
  post-void residual significant > 50 ml
  liver span       hepatomegaly > 160 mm
  spleen span      splenomegaly > 130 mm
"""
FILES_VERSION = "2026-10-11"   # must match streamlit_app.py


PROSTATE_GRADES = [(30, None), (50, 'mild'), (80, 'moderate'), (10_000, 'severe')]
PVR_SIGNIFICANT_ML = 50

# patient-specific evaluation (age/sex from the report's patient table)
PAEDIATRIC_BELOW_YEARS = 16          # adult cut-offs (liver, spleen, kidney, prostate) not applied below this
ADULT_KIDNEY_MM = (80, 130)          # outside this an adult kidney length is flagged for review
                                     # (archive: normal-study kidneys 5th-95th centile 82-113 mm, max 122 mm)
LIVER_ENLARGED_MM = 160
SPLEEN_ENLARGED_MM = 130

TITLES = {
    'abdomen': 'ABDOMINOPELVIC ULTRASOUND SCAN',
    'breast': 'BREAST ULTRASOUND',
}

# ---- normal / measured paragraphs (abdominopelvic) -------------------------------
LIVER_NORMAL = ("The liver is normal in size and showed uniform parenchymal echopattern.{span} "
                "No intrahepatic mass or collection is seen. The intrahepatic biliary ducts and vascular "
                "channels are not dilated.")
LIVER_SPAN = " It measures {v:.2f}mm in cranio-caudal span."
LIVER_ENLARGED = ("The liver is mildly enlarged with uniform parenchymal echopattern. It measured {v:.2f}mm in "
                  "cranio-caudal span. The intrahepatic biliary ducts and vascular channels are not dilated. "
                  "No intra-hepatic mass or collection was seen.")
GALLBLADDER_NORMAL = ("The gall bladder is normal in caliber with clear luminal content. No calculus is seen "
                      "and its wall not thickened.")
KIDNEYS_NORMAL = ("Both kidneys are normal in position, shape, size and outline. They showed good "
                  "corticomedullary distinction and central sinus echoes. No calculus or dilatation is seen.{size}")
KIDNEYS_SIZE = " They measure {r:.2f}mm and {l:.2f}mm in bipolar length on the right and left."
KIDNEY_ONE_SIZE = " The {side} kidney measures {v:.2f}mm in bipolar length."
SPLEEN_PARA = "The pancreas, para-aortic areas and spleen{spl} appear within normal limits."
SPLEEN_ENLARGED = ("The spleen is mildly enlarged measuring {v:.2f}mm in cranio-caudal span. It showed uniform "
                   "parenchymal echopattern. No mass or collection is seen within it. The pancreas and "
                   "para-aortic areas appear within normal limits.")
BOWEL = ("No intra-abdominal mass or collection is seen. The bowel loops showed normal caliber and "
         "peristaltic activity.")
BLADDER = ("The urinary bladder is distended with urine and showed normal mucosal wall thickness. "
           "No intraluminal mass or calculus was seen.{pvr}")
PVR_NIL = " Nil significant PVR ({v:.2f}ml) was noted."
PVR_SIG = " There is significant PVR of urine measuring {v:.2f}ml."
PROSTATE_NORMAL = "The prostate gland ({v:.2f}ml) also appeared within normal limits."
PROSTATE_NORMAL_NOVOL = "The prostate gland also appeared within normal limits."
PROSTATE_ENLARGED = ("The prostate gland is {grade}ly enlarged with regular outline and intact capsule. "
                     "It measured about {v:.2f}cm3. No calcification or cystic change/degeneration is seen.")
UTERUS_NORMAL = "The uterus{ap} also appeared within normal limits."
UTERUS_AP = " ({v:.2f}mm)"

# ---- breast ----------------------------------------------------------------------
BREAST_DENSITY = "Heterogenous fibroglandular tissue in keeping with type III parenchymal density pattern."
BREAST_NO_MASS = "No intra-mammary mass or collection is seen."
BREAST_NIPPLE = ("The nipples, retro-mammary spaces, pectoralis muscles and axillary tail appeared within "
                 "normal limits.")
BREAST_NODES = "Few lymph nodes were seen in the axilla bilaterally, with an average diameter of about {v:.2f}mm."
BREAST_INDICATION = "ROUTINE"

# ---- conclusions -------------------------------------------------------------------
CONCL_NORMAL = "Normal Study"
CONCL_PAEDIATRIC_REVIEW = "[Radiologist to complete: compare paediatric measurements with age charts]"
CONCL_NORMAL_BREAST = "Normal study (BIRADS 1)."
CONCL_PROSTATE = "{Grade} prostate gland enlargement likely due to BPH{pvr}."
CONCL_PVR = " with significant PVR"
CONCL_HEPATOMEGALY = "Mild hepatomegaly."
CONCL_SPLENOMEGALY = "Mild splenomegaly ?cause."
ADVICE_PSA = "PSA is advised for further evaluation."

# ---- findings the reader can add with one click -----------------------------------
# Measurements cannot see these on the image; the reader confirms them. 'replaces' names the
# organ paragraph the wording replaces. Wording is the radiologist's own most frequent phrasing.
FINDINGS = {
    'fatty_liver': {
        'label': 'Fatty liver (grade I)', 'exam': 'abdomen', 'replaces': 'liver',
        'text': ("The liver is normal in size{span_c} It showed slightly increased parenchymal echogenicity "
                 "probably due to fatty infiltration. No intrahepatic mass or collection is seen. The intrahepatic "
                 "biliary ducts and vascular channels are not dilated."),
        'conclusion': 'Fatty liver (grade I).'},
    'cld': {
        'label': 'Chronic liver disease (coarse, irregular liver)', 'exam': 'abdomen', 'replaces': 'liver',
        'text': ("The liver{span_m} showed irregular outline with coarsened parenchymal echotexture. No intrahepatic "
                 "mass or collection is seen. The intrahepatic biliary ducts and vascular channels are not dilated."),
        'conclusion': 'Features are those of CLD.'},
    'pyelo_left': {
        'label': 'Left pyelonephritis', 'exam': 'abdomen', 'replaces': 'kidneys',
        'text': ("Both kidneys are normal in position, shape, size and outline.{size} The left kidney show prominence "
                 "of its pyramids with slight patchy parenchymal echogenicity. The right kidney appears within "
                 "normal limits."),
        'conclusion': 'Features are suggestive of left pyelonephritis.'},
    'pyelo_right': {
        'label': 'Right pyelonephritis', 'exam': 'abdomen', 'replaces': 'kidneys',
        'text': ("Both kidneys are normal in position, shape, size and outline.{size} The right kidney show prominence "
                 "of its pyramids with slight patchy parenchymal echogenicity. The left kidney appears within "
                 "normal limits."),
        'conclusion': 'Features are suggestive of right pyelonephritis.'},
    'pyelo_bilateral': {
        'label': 'Bilateral pyelonephritis', 'exam': 'abdomen', 'replaces': 'kidneys',
        'text': ("Both kidneys are normal in position, shape, size and outline.{size} They showed decreased "
                 "echogenicity with slight prominence of the medullary pyramids. No calculus or calyceal "
                 "dilatation was seen."),
        'conclusion': 'Features are suggestive of bilateral pyelonephritis.'},
    'renal_cyst_left': {
        'label': 'Left renal cortical cyst', 'exam': 'abdomen', 'replaces': None,
        'text': "The left kidney show cortical cystic lesion at the lower pole region. No calculus or calyceal dilatation is seen.",
        'conclusion': 'Left renal cortical cyst.'},
    'renal_cyst_right': {
        'label': 'Right renal cortical cyst', 'exam': 'abdomen', 'replaces': None,
        'text': "There is a small right renal cortical cystic lesion. No calculus or calyceal dilatation is seen.",
        'conclusion': 'Right renal cortical cyst.'},
    'cholelithiasis': {
        'label': 'Gallstones (non-obstructive)', 'exam': 'abdomen', 'replaces': 'gallbladder',
        'text': ("The gall bladder is normal in caliber with echogenic calculi within its lumen casting posterior "
                 "acoustic shadows. Its wall is not thickened."),
        'conclusion': 'Non obstructive cholelithiasis.'},
    'fibroid': {
        'label': 'Uterine fibroid', 'exam': 'abdomen', 'replaces': 'uterus',
        'text': ("The uterus is mildly enlarged though empty.{ap_c} There is an oval mixed echogenic mass within the "
                 "myometrium in keeping with a fibroid nodule.{fib_size} Both adnexae are free."),
        'conclusion': 'Uterine fibroid.'},
    'fibroadenoma': {
        'label': 'Fibroadenoma (BIRADS 3)', 'exam': 'breast', 'replaces': 'breast_mass',
        'text': ("There is a small fairly oval hypoechoic nodule in the breast.{lesion_size} The nodule showed slight posterior "
                 "acoustic enhancement. No calcification or cystic change is seen."),
        'conclusion': 'Small fibroadenoma (BIRADS 3).'},
}
