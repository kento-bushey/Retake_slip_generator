# Retake Slip Generator & PowerSchool Scoresheet Converter

A desktop utility for teachers to process PowerSchool Scoresheet PDFs into CSV spreadsheets and automatically generate printable $3 \times 8$ grid retake slips for students.

---

## 📌 How to Export the Scoresheet Report from PowerSchool

1. Log into **PowerSchool**.
2. Select your class from the dashboard and open **PowerTeacher Pro**.
3. In the left sidebar, click on **Reports** $\rightarrow$ select **Scoresheet Report**.
4. Configure the report options:
   - **Student Sort**: Sort by Student Name.
   - **Items to Include**: Ensure Checkpoint Assignment Scores are visible.
   - **Format**: Select **PDF**.
5. Click **Run Report**, then download the generated PDF file to your computer.

---

## 🚀 Running the App

1. Download the latest `Retake_Slip_Generator_v1.0.0.zip` from the **Releases** section on GitHub.
2. Extract the contents of the ZIP file to a folder on your computer.
3. Double-click **`Retake_Slip_Generator.exe`** to launch the program.

---

## ⚙️ App Features & Usage

1. **Select Scoresheet PDF**: Click **Select PDF** to load your exported PowerSchool report.
2. **Select Checkpoint Pair**: Click on an assignment (e.g., *Checkpoint 1A*). The application will automatically select its matching pair (*Checkpoint 1B*).
3. **Convert to CSV**: Exports all extracted student grades into a clean `.csv` file.
4. **Generate Retake Slips PDF**: Compiles printable retake slips in a $3 \times 8$ grid. Students with a best score of $4.0/4.0$ are automatically omitted.
5. **Name Changes (✏ Name Changes)**: Override default PowerSchool student names with custom display nicknames. Click the `❓` symbol inside the manager for additional details.
