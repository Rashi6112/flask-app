from flask import Flask, request, send_file, render_template
import pandas as pd
import os

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

def consolidate_and_filter_materials(input_path):
    df = pd.read_excel(input_path, engine='openpyxl')

    # Debugging: Print column names
    print("Columns in the file:", df.columns)

    # Remove spaces from column names
    df.columns = df.columns.str.strip()

    # Ensure correct column name mapping
    if 'Material Code' not in df.columns:
        raise KeyError("Column 'Material Code' not found in the file. Available columns: " + ", ".join(df.columns))

    combine_df = df.groupby('Material Code').agg({
        'Last Recpt. Date': 'min',
        'Material Description': 'first',
        'ACTUAL QTY': 'sum',
        'ACTUAL VALUE': 'sum',
        'MRP Type': 'first',
        'Aging': 'max'
    }).reset_index()

    combine_df.rename(columns={
        'Last Recpt. Date': 'Document Date (Oldest)',
        'Material Description': 'Material Description',
        'ACTUAL VALUE': 'Total Amount in Local Currency',
        'Aging': 'Max Aging Days'
    }, inplace=True)

    filtered_df = combine_df[combine_df['Max Aging Days'] > 365]
    data = filtered_df[filtered_df['MRP Type'] != 'VB']

    temp_file = os.path.join(PROCESSED_FOLDER, 'temp_filtered.xlsx')
    data.to_excel(temp_file, index=False)
    return temp_file

def remove_matching_rows(temp_file, g1_g2_file, flagged_file):
    filtered_df = pd.read_excel(temp_file)
    g1_g2_df = pd.read_excel(g1_g2_file)
    flagged_df = pd.read_excel(flagged_file)

    filtered_df.rename(columns={'Material Number': 'Material Code'}, inplace=True)
    g1_g2_df.rename(columns={'Material Code': 'Material Code'}, inplace=True)
    flagged_df.rename(columns={'Material Code': 'Material Code', 'Flag': 'Flag_from_flagged'}, inplace=True)

    final_df = filtered_df[~filtered_df['Material Code'].isin(g1_g2_df['Material Code'])]

    def determine_flag(row):
        if row['MRP Type'] in ['ES', 'IA'] and row['Max Aging Days'] > 365:
            return 'G9'
        elif row['MRP Type'] == 'SP' and 729 < row['Max Aging Days'] < 1085:
            if row['Total Amount in Local Currency'] < 10000:
                return 'G6'
            else:
                return 'G7'
        elif row['MRP Type'] == 'SP' and row['Max Aging Days'] > 1086:
            return 'G3'
        elif row['MRP Type'] == 'SP' and 365 < row['Max Aging Days'] < 730:
            return 'G9'
        else:
            return ''

    final_df['Flag'] = final_df.apply(determine_flag, axis=1)
    final_df = final_df.merge(flagged_df[['Material Code', 'Flag_from_flagged']], on='Material Code', how='left')
    final_df['Flag_Mismatch'] = final_df['Flag'] != final_df['Flag_from_flagged']
    final_df = final_df[(final_df['Flag_Mismatch']) & (final_df['Flag_from_flagged'] != 'S1')]
    final_df = final_df.drop(columns=['Flag_Mismatch'])
    final_df = final_df[final_df['ACTUAL QTY'] > 0]

    final_output_file = os.path.join(PROCESSED_FOLDER, 'final_output.xlsx')
    final_df.to_excel(final_output_file, index=False)
    return final_output_file

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload_files():
    if 'plant' not in request.files or 'g1_g2' not in request.files or 'flagged' not in request.files:
        return "All three files are required", 400

    plant = request.files['plant']
    g1_g2 = request.files['g1_g2']
    flagged = request.files['flagged']

    if plant.filename == '' or g1_g2.filename == '' or flagged.filename == '':
        return "All files must be selected", 400

    plant_path = os.path.join(UPLOAD_FOLDER, plant.filename)
    g1_g2_path = os.path.join(UPLOAD_FOLDER, g1_g2.filename)
    flagged_path = os.path.join(UPLOAD_FOLDER, flagged.filename)

    plant.save(plant_path)
    g1_g2.save(g1_g2_path)
    flagged.save(flagged_path)

    temp_file = consolidate_and_filter_materials(plant_path)
    final_output = remove_matching_rows(temp_file, g1_g2_path, flagged_path)

    return send_file(final_output, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)  