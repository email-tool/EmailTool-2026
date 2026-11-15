
import os
import pandas as pd
def file_load(file_path):
    # Determine file extension
    _, file_extension = os.path.splitext(file_path)
    
    # Load the data
    if file_extension == ".csv":
        # Try multiple encodings for files saved from Excel
        encodings = ['utf-8', 'utf-16', 'utf-16-le', 'latin-1', 'windows-1252']
        data = None
        for encoding in encodings:
            try:
                data = pd.read_csv(file_path, encoding=encoding)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if data is None:
            raise ValueError(f"Could not read CSV file. Tried encodings: {encodings}")
    elif file_extension in [".xls", ".xlsx"]:
        # Read up to 5 sheets and append data into one DataFrame
        excel_data = pd.ExcelFile(file_path)
        sheets = excel_data.sheet_names[:5]  # Get the first 5 sheets
        data = pd.concat([excel_data.parse(sheet) for sheet in sheets], ignore_index=True)
    else:
        raise ValueError("Unsupported file format. Only CSV and Excel files are allowed.")
    
    return data