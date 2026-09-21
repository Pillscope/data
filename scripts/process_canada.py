import csv, json, os
from collections import defaultdict

BASE = os.path.expanduser("~/data/canada/marketed")
OUT = os.path.expanduser("~/data/canada/processed")
os.makedirs(OUT, exist_ok=True)

def load(name, cols):
    path = os.path.join(BASE, name)
    rows = defaultdict(list)
    with open(path, encoding="latin-1") as f:
        for row in csv.reader(f):
            if len(row) < len(cols):
                continue
            record = dict(zip(cols, row))
            rows[record["DRUG_CODE"]].append(record)
    return rows

drugs = load("drug.txt", ["DRUG_CODE","PRODUCT_CATEGORIZATION","CLASS","DIN","BRAND_NAME","DESCRIPTOR","PEDIATRIC_FLAG","ACCESSION_NUMBER","NUMBER_OF_AIS","LAST_UPDATE_DATE","AI_GROUP_NO","CLASS_F","BRAND_NAME_F","DESCRIPTOR_F"])
ingredients = load("ingred.txt", ["DRUG_CODE","ACTIVE_INGREDIENT_CODE","INGREDIENT","INGREDIENT_SUPPLIED_IND","STRENGTH","STRENGTH_UNIT","STRENGTH_TYPE","DOSAGE_VALUE","BASE","DOSAGE_UNIT","NOTES","INGREDIENT_F","STRENGTH_UNIT_F","STRENGTH_TYPE_F","DOSAGE_UNIT_F"])
forms = load("form.txt", ["DRUG_CODE","PHARM_FORM_CODE","PHARMACEUTICAL_FORM","PHARMACEUTICAL_FORM_F"])
routes = load("route.txt", ["DRUG_CODE","ROUTE_OF_ADMINISTRATION_CODE","ROUTE_OF_ADMINISTRATION","ROUTE_OF_ADMINISTRATION_F"])
companies = load("comp.txt", ["DRUG_CODE","MFR_CODE","COMPANY_CODE","COMPANY_NAME","COMPANY_TYPE","ADDR_MAIL_FLAG","ADDR_BILL_FLAG","ADDR_NOTIFY_FLAG","ADDR_OTHER","SUITE","STREET","CITY","PROVINCE","COUNTRY","POSTAL_CODE","PO_BOX","PROVINCE_F","COUNTRY_F"])
statuses = load("status.txt", ["DRUG_CODE","CURRENT_STATUS_FLAG","STATUS","HISTORY_DATE","STATUS_F","LOT_NUMBER","EXPIRATION_DATE"])
therapeutic = load("ther.txt", ["DRUG_CODE","ATC_NUMBER","ATC","AHFS_NUMBER","AHFS","ATC_F","AHFS_F"])

index = []
for code, drug_rows in drugs.items():
    d = drug_rows[0]
    record = {
        "drug_code": code,
        "din": d["DIN"],
        "brand_name": d["BRAND_NAME"],
        "class": d["CLASS"],
        "descriptor": d["DESCRIPTOR"],
        "last_update": d["LAST_UPDATE_DATE"],
        "active_ingredients": [
            {"name": i["INGREDIENT"], "strength": i["STRENGTH"], "unit": i["STRENGTH_UNIT"]}
            for i in ingredients.get(code, [])
        ],
        "forms": [f["PHARMACEUTICAL_FORM"] for f in forms.get(code, [])],
        "routes": [r["ROUTE_OF_ADMINISTRATION"] for r in routes.get(code, [])],
        "companies": [c["COMPANY_NAME"] for c in companies.get(code, [])],
        "status": statuses.get(code, [{}])[0].get("STATUS", ""),
        "atc": [t["ATC"] for t in therapeutic.get(code, [])],
    }
    with open(os.path.join(OUT, f"{code}.json"), "w") as f:
        json.dump(record, f, indent=2)
    index.append({"drug_code": code, "din": d["DIN"], "brand_name": d["BRAND_NAME"]})

with open(os.path.join(OUT, "_index.json"), "w") as f:
    json.dump(index, f, indent=2)

print(f"Processed {len(index)} drugs into {OUT}")
