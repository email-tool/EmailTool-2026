import argparse
import sys
from pathlib import Path

import pandas as pd


COMPANY_HEADERS = (
    "company",
    "company name",
    "companyname",
    "organisation",
    "organization",
    "org",
    "account",
    "account name",
    "employer",
    "business",
    "business name",
)
EMAIL_HEADERS = (
    "email",
    "email address",
    "emailaddress",
    "e mail",
    "e-mail",
    "mail",
    "email id",
    "work email",
    "business email",
    "corporate email",
)
CONTACT_HEADERS = (
    "contact name",
    "full name",
    "fullname",
    "name",
    "person",
    "person name",
    "employee",
    "employee name",
)
FIRST_NAME_HEADERS = ("first name", "firstname", "first", "fname", "given name", "forename")
LAST_NAME_HEADERS = ("last name", "lastname", "last", "lname", "surname", "family name")
CSV_ENCODINGS = ("utf-8", "utf-16", "utf-16-le", "latin-1", "windows-1252")


def normalize_header(value):
    return " ".join(str(value).lower().replace("_", " ").replace("-", " ").split())


def find_column(dataframe, accepted_names):
    columns = {normalize_header(column): column for column in dataframe.columns}
    return next((columns[name] for name in accepted_names if name in columns), None)


def read_data_file(file_path):
    extension = file_path.suffix.lower()
    if extension == ".csv":
        for encoding in CSV_ENCODINGS:
            try:
                return pd.read_csv(file_path, dtype=str, encoding=encoding), None
            except UnicodeError:
                continue
        raise ValueError(f"Could not decode CSV using: {', '.join(CSV_ENCODINGS)}")

    if extension in (".xlsx", ".xls"):
        workbook = pd.ExcelFile(file_path)
        if not workbook.sheet_names:
            raise ValueError("The workbook has no worksheets")
        sheet_name = workbook.sheet_names[0]
        return workbook.parse(sheet_name, dtype=str), sheet_name

    raise ValueError("Supported file types are .csv, .xlsx, and .xls")


def present_values(dataframe, column):
    if column is None:
        return pd.Series(False, index=dataframe.index)
    return dataframe[column].fillna("").astype(str).str.strip().ne("")


def inspect_file(file_path):
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    dataframe, sheet_name = read_data_file(file_path)
    company_column = find_column(dataframe, COMPANY_HEADERS)
    email_column = find_column(dataframe, EMAIL_HEADERS)
    contact_column = find_column(dataframe, CONTACT_HEADERS)
    first_name_column = find_column(dataframe, FIRST_NAME_HEADERS)
    last_name_column = find_column(dataframe, LAST_NAME_HEADERS)

    company_present = present_values(dataframe, company_column)
    email_present = present_values(dataframe, email_column)
    contact_present = present_values(dataframe, contact_column)

    if first_name_column and last_name_column:
        split_name_present = (
            present_values(dataframe, first_name_column)
            & present_values(dataframe, last_name_column)
        )
        contact_present |= split_name_present

    if company_column is None:
        unique_companies = 0
        duplicate_company_rows = 0
    else:
        normalized_companies = (
            dataframe[company_column]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.casefold()
        )
        nonblank_companies = normalized_companies[normalized_companies.ne("")]
        unique_companies = int(nonblank_companies.nunique())
        duplicate_company_rows = len(nonblank_companies) - unique_companies

    if email_column is None:
        email_without_at = 0
    else:
        email_values = dataframe[email_column].fillna("").astype(str).str.strip()
        email_without_at = int((email_present & ~email_values.str.contains("@", regex=False)).sum())

    total_rows = len(dataframe)
    complete_rows = company_present & email_present & contact_present

    return {
        "file": file_path,
        "sheet": sheet_name,
        "rows": total_rows,
        "company_column": company_column,
        "email_column": email_column,
        "contact_column": contact_column or (
            f"{first_name_column} + {last_name_column}"
            if first_name_column and last_name_column
            else None
        ),
        "unique_companies": unique_companies,
        "duplicate_company_rows": duplicate_company_rows,
        "missing_company": int((~company_present).sum()),
        "missing_email": int((~email_present).sum()),
        "missing_contact": int((~contact_present).sum()),
        "email_without_at": email_without_at,
        "complete_rows": int(complete_rows.sum()),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Check row, company, contact-name, and email completeness in a CSV or Excel file."
    )
    parser.add_argument("path", nargs="?", help="Path to a .csv, .xlsx, or .xls file")
    args = parser.parse_args()
    input_path = args.path or input("Path to CSV or Excel file: ").strip().strip('"')

    try:
        result = inspect_file(Path(input_path).expanduser())
    except Exception as error:
        print(f"Could not inspect file: {error}", file=sys.stderr)
        return 1

    print(f"File: {result['file']}")
    if result["sheet"]:
        print(f"Worksheet: {result['sheet']} (first worksheet only)")
    print(f"Total data rows: {result['rows']:,}")
    print(f"Company column: {result['company_column'] or 'NOT FOUND'}")
    print(f"Contact-name column(s): {result['contact_column'] or 'NOT FOUND'}")
    print(f"Email column: {result['email_column'] or 'NOT FOUND'}")
    print(f"Unique nonblank companies: {result['unique_companies']:,}")
    print(f"Rows beyond one per company: {result['duplicate_company_rows']:,}")
    print(f"Rows with company, contact name, and email: {result['complete_rows']:,}")
    print(f"Rows missing company: {result['missing_company']:,}")
    print(f"Rows missing contact name: {result['missing_contact']:,}")
    print(f"Rows missing email: {result['missing_email']:,}")
    print(f"Present emails without @: {result['email_without_at']:,}")
    print("Note: email validation only checks for @; it does not verify deliverability.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())