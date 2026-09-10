import json
import os
import re
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pandas as pd
import pdfplumber

CONFIG_FILE = "config.json"
NICKNAMES_FILE = "nicknames.json"


# ----------------------------------------------------------------------
# Helper Storage Functions
# ----------------------------------------------------------------------
def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


# ----------------------------------------------------------------------
# PDF Extraction Engine
# ----------------------------------------------------------------------
def parse_scoresheet_pdf(pdf_path):
    student_records = {}
    all_assignments = []
    period_number = "1"

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""

            period_match = re.search(
                r"Class:\s*(\d+)", text, re.IGNORECASE
            ) or re.search(r"\bP(\d+)\b", text)
            if period_match and period_number == "1":
                period_number = period_match.group(1)

            tables = page.extract_tables()
            if not tables:
                continue

            for table in tables:
                if not table or len(table) < 2:
                    continue

                header_row = table[0]
                page_assignments = []

                for cell in header_row:
                    if not cell:
                        page_assignments.append(None)
                        continue

                    clean_header = cell.replace("\n", " ").strip()
                    clean_header = re.sub(
                        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+.*",
                        "",
                        clean_header,
                        flags=re.IGNORECASE,
                    )
                    clean_header = re.sub(
                        r"PTS\s+\d+.*", "", clean_header, flags=re.IGNORECASE
                    )
                    clean_header = re.sub(
                        r"x\s*\d+(\.\d+)?", "", clean_header, flags=re.IGNORECASE
                    )
                    clean_header = re.sub(r"\s+", " ", clean_header).strip()

                    if (
                        clean_header
                        and "Scoresheet" not in clean_header
                        and "Class:" not in clean_header
                        and "P1" not in clean_header
                    ):
                        page_assignments.append(clean_header)
                        if clean_header not in all_assignments:
                            all_assignments.append(clean_header)
                    else:
                        page_assignments.append(None)

                for row in table[1:]:
                    if not row or not any(row):
                        continue

                    row_str = " ".join([str(c) for c in row if c])
                    if "Class:" in row_str or "Scoresheet" in row_str:
                        continue

                    first_cell = row[0] if row[0] else ""
                    name_match = re.search(
                        r"([A-Za-z\s\.\'-]+,\s+[A-Za-z\s\.\'-]+)", first_cell
                    ) or re.search(
                        r"([A-Za-z\s\.\'-]+,\s+[A-Za-z\s\.\'-]+)", row_str
                    )

                    if not name_match:
                        continue

                    student_name = name_match.group(1).strip()
                    student_name = re.sub(r"\s+[A-F]$", "", student_name)

                    overall_grade = ""
                    grade_match = re.search(r"([A-F]\s+\d+(\.\d+)?%)", row_str)
                    if grade_match:
                        overall_grade = grade_match.group(1).strip()

                    if student_name not in student_records:
                        student_records[student_name] = {
                            "Grade": overall_grade,
                            "Scores": {},
                        }
                    elif overall_grade and not student_records[student_name]["Grade"]:
                        student_records[student_name]["Grade"] = overall_grade

                    for col_idx, assign_name in enumerate(page_assignments):
                        if assign_name and col_idx < len(row):
                            cell_val = row[col_idx]
                            if cell_val:
                                score_match = re.search(
                                    r"\b\d+(?:\.\d+)?\b", str(cell_val)
                                )
                                if score_match:
                                    score = score_match.group(0)
                                    if float(score) <= 4.0:
                                        student_records[student_name]["Scores"][
                                            assign_name
                                        ] = score

    return student_records, all_assignments, period_number


def extract_scoresheet_to_csv(pdf_path, output_csv_path):
    student_records, all_assignments, _ = parse_scoresheet_pdf(pdf_path)
    sorted_students = sorted(student_records.keys())

    output_rows = []
    for student in sorted_students:
        entry = {
            "Student Name": student,
            "Overall Grade": student_records[student]["Grade"],
        }
        for assign in all_assignments:
            entry[assign] = student_records[student]["Scores"].get(assign, "")
        output_rows.append(entry)

    df = pd.DataFrame(output_rows)
    df.to_csv(output_csv_path, index=False)


# ----------------------------------------------------------------------
# Name Formatting & Helpers
# ----------------------------------------------------------------------
def format_display_name(raw_name, nicknames):
    if raw_name in nicknames and nicknames[raw_name].strip():
        return nicknames[raw_name].strip()

    parts = raw_name.split(",")
    if len(parts) == 2:
        last_name = parts[0].strip()
        first_and_middle = parts[1].strip().split()
        first_name = first_and_middle[0] if first_and_middle else ""
        last_initial = last_name[0].upper() + "." if last_name else ""
        return f"{first_name} {last_initial}".strip()

    return raw_name


def extract_chkpt_number(title):
    match = re.search(r"\b(\d+[A-Za-z]?)\b", title)
    if match:
        num_only = re.sub(r"[A-Za-z]", "", match.group(1))
        return num_only if num_only else match.group(1)
    return ""


# ----------------------------------------------------------------------
# ReportLab Native PDF Fallback
# ----------------------------------------------------------------------
def generate_native_pdf_slips(
    student_records, chk1, chk2, period_str, chk_num, output_pdf_path, nicknames
):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(output_pdf_path, pagesize=letter)
    page_width, page_height = letter

    cols, rows = 3, 8
    margin_x, margin_y = 18, 18
    box_width = (page_width - (2 * margin_x)) / cols
    box_height = (page_height - (2 * margin_y)) / rows

    sorted_students = sorted(student_records.keys())
    valid_student_count = 0

    for student_raw in sorted_students:
        scores_dict = student_records[student_raw]["Scores"]
        val1_str = scores_dict.get(chk1, "N/A")
        val2_str = scores_dict.get(chk2, "N/A")

        valid_scores = []
        for v in [val1_str, val2_str]:
            try:
                valid_scores.append(float(v))
            except ValueError:
                pass

        best_num = max(valid_scores) if valid_scores else 0
        if best_num >= 4.0:
            continue

        page_idx = valid_student_count % 24
        if valid_student_count > 0 and page_idx == 0:
            c.showPage()

        col = page_idx % cols
        row = page_idx // cols

        x = margin_x + col * box_width
        y = page_height - margin_y - (row + 1) * box_height

        c.setLineWidth(0.5)
        c.setStrokeColor(colors.gray)
        c.rect(x + 2, y + 2, box_width - 4, box_height - 4)

        display_name = format_display_name(student_raw, nicknames)
        best_score_str = (
            f"{best_num:.1f}".rstrip("0").rstrip(".") + "/4"
            if valid_scores
            else "N/A"
        )
        s1_display = f"{val1_str}/4" if val1_str != "N/A" else "N/A"
        s2_display = f"{val2_str}/4" if val2_str != "N/A" else "N/A"

        label1 = chk1.split("-")[0].strip() if "-" in chk1 else chk1
        label2 = chk2.split("-")[0].strip() if "-" in chk2 else chk2

        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(x + 6, y + box_height - 11, "Retake Slip")

        c.setFont("Helvetica", 6)
        c.drawRightString(x + box_width - 8, y + box_height - 11, f"Per {period_str}")

        c.setFont("Helvetica-Bold", 8)
        c.drawString(x + 6, y + box_height - 21, f"Checkpoint #{chk_num}")

        c.setFont("Helvetica-Bold", 11)
        c.drawString(x + 6, y + box_height - 38, display_name)

        c.setFont("Helvetica", 6)
        c.drawString(x + 6, y + box_height - 49, f"{label1}: {s1_display}")
        c.drawString(x + 6, y + box_height - 56, f"{label2}: {s2_display}")

        box_x = x + box_width - 55
        box_y = y + box_height - 52
        c.rect(box_x, box_y, 48, 26)
        c.setFont("Helvetica", 5)
        c.drawCentredString(box_x + 24, box_y + 18, "BEST SCORE")
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(box_x + 24, box_y + 6, best_score_str)

        c.setFont("Helvetica", 4.5)
        c.drawString(
            x + 6,
            y + 9,
            "Come to tutoring for retakes, you can retake",
        )
        c.drawString(
            x + 6,
            y + 4.5,
            "this checkpoint on your second tutoring visit.",
        )

        valid_student_count += 1

    c.save()


# ----------------------------------------------------------------------
# Absolute Coordinate TikZ Slip Generator (Manual Line Spacing)
# ----------------------------------------------------------------------
def generate_latex_slips(
    pdf_path, chk1, chk2, period, output_pdf_path, nicknames, progress_cb=None
):
    student_records, _, auto_period = parse_scoresheet_pdf(pdf_path)
    period_str = str(period if period else auto_period)
    chk_num = extract_chkpt_number(chk1)
    sorted_students = sorted(student_records.keys())

    pdflatex_bin = shutil.which("pdflatex")

    if not pdflatex_bin:
        generate_native_pdf_slips(
            student_records,
            chk1,
            chk2,
            period_str,
            chk_num,
            output_pdf_path,
            nicknames,
        )
        return

    tex_filename = output_pdf_path.replace(".pdf", ".tex")

    latex_code = [
        r"\documentclass[letterpaper,10pt]{article}",
        r"\usepackage[margin=0.2in]{geometry}",
        r"\usepackage{tikz}",
        r"\usepackage{xcolor}",
        r"\pagestyle{empty}",
        r"",
        r"% Explicit 2-line bottom text placement to manually control gap",
        r"\newcommand{\RetakeSlip}[6]{%",
        r"  \begin{tikzpicture}",
        r"    % Card Border Box",
        r"    \draw[thick, rounded corners=2pt] (0,0) rectangle (6.3, 3.0);",
        r"",
        r"    % Top Header Row",
        r"    \node[anchor=north west] at (0.15, 2.85) {{\textbf{\scriptsize Retake Slip}}};",
        r"    \node[anchor=north east] at (6.15, 2.85) {{\textbf{\tiny Per "
        + period_str
        + r"}}};",
        r"",
        r"    % Checkpoint # Header",
        r"    \node[anchor=north west] at (0.15, 2.45) {{\small \textbf{Checkpoint \#"
        + chk_num
        + r"}}};",
        r"",
        r"    % Student Display Name (Prominent & Clear)",
        r"    \node[anchor=north west] at (0.15, 2.00) {{\Large \textbf{#1}}};",
        r"",
        r"    % Checkpoint Scores Stack",
        r"    \node[anchor=north west] at (0.15, 1.35) {{\tiny #2: \textbf{#3}}};",
        r"    \node[anchor=north west] at (0.15, 1.05) {{\tiny #4: \textbf{#5}}};",
        r"",
        r"    % Best Score Box",
        r"    \draw[fill=gray!10, rounded corners=1pt] (4.4, 0.85) rectangle (6.15, 1.75);",
        r"    \node[anchor=center] at (5.275, 1.50) {{\tiny BEST SCORE}};",
        r"    \node[anchor=center] at (5.275, 1.15) {{\small \textbf{#6}}};",
        r"",
        r"    % Bottom Instructions: Separated into 2 discrete lines placed 0.18cm apart",
        r"    \node[anchor=south west] at (0.15, 0.28) {{\fontsize{4.8pt}{5.0pt}\selectfont Come to tutoring for retakes, you can retake}}; ",
        r"    \node[anchor=south west] at (0.15, 0.10) {{\fontsize{4.8pt}{5.0pt}\selectfont this checkpoint on your second tutoring visit.}}; ",
        r"  \end{tikzpicture}%",
        r"}",
        r"",
        r"\begin{document}",
    ]

    slips_buffer = []
    label1 = chk1.split("-")[0].strip() if "-" in chk1 else chk1
    label2 = chk2.split("-")[0].strip() if "-" in chk2 else chk2

    for student_raw in sorted_students:
        scores_dict = student_records[student_raw]["Scores"]
        val1_str = scores_dict.get(chk1, "N/A")
        val2_str = scores_dict.get(chk2, "N/A")

        valid_scores = []
        for v in [val1_str, val2_str]:
            try:
                valid_scores.append(float(v))
            except ValueError:
                pass

        best_num = max(valid_scores) if valid_scores else 0
        if best_num >= 4.0:
            continue

        display_name = format_display_name(student_raw, nicknames)
        display_name_tex = (
            display_name.replace("&", r"\&")
            .replace("_", r"\_")
            .replace("#", r"\#")
        )

        best_score_str = (
            f"{best_num:.1f}".rstrip("0").rstrip(".") + "/4"
            if valid_scores
            else "N/A"
        )
        s1_display = f"{val1_str}/4" if val1_str != "N/A" else "N/A"
        s2_display = f"{val2_str}/4" if val2_str != "N/A" else "N/A"

        macro_call = f"\\RetakeSlip{{{display_name_tex}}}{{{label1}}}{{{s1_display}}}{{{label2}}}{{{s2_display}}}{{{best_score_str}}}"
        slips_buffer.append(macro_call)

    # Build 3-column x 8-row grid
    total_slips = len(slips_buffer)
    for i in range(0, total_slips, 24):
        page_slips = slips_buffer[i : i + 24]
        latex_code.append(r"\noindent")
        latex_code.append(r"\begin{tabular}{@{}c@{\hspace{0.02in}}c@{\hspace{0.02in}}c@{}}")

        for idx, slip in enumerate(page_slips):
            latex_code.append(slip)
            if (idx + 1) % 3 == 0:
                latex_code.append(r"\\[0.01in]")
            else:
                latex_code.append(r" & ")

        latex_code.append(r"\end{tabular}")
        if i + 24 < total_slips:
            latex_code.append(r"\newpage")

    latex_code.append(r"\end{document}")

    clean_tex = "\n".join(latex_code)

    with open(tex_filename, "w", encoding="utf-8") as f:
        f.write(clean_tex)

    out_dir = os.path.dirname(output_pdf_path)
    cmd = f'"{pdflatex_bin}" -interaction=nonstopmode -output-directory="{out_dir}" "{tex_filename}"'

    subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
    )


# ----------------------------------------------------------------------
# GUI Dialog Windows
# ----------------------------------------------------------------------
class NicknameManagerDialog(tk.Toplevel):

    def __init__(self, parent, pdf_path, nicknames):
        super().__init__(parent)
        self.title("Manage Student Nicknames")
        self.geometry("450x400")
        self.nicknames = nicknames
        self.entries = {}

        # Modal window configuration
        self.transient(parent)
        self.grab_set()

        tk.Label(
            self,
            text="Set Nicknames (Overrides Default Name):",
            font=("Arial", 10, "bold"),
        ).pack(pady=10)

        container = tk.Frame(self)
        container.pack(fill="both", expand=True, padx=10, pady=5)

        canvas = tk.Canvas(container)
        scrollbar = ttk.Scrollbar(
            container, orient="vertical", command=canvas.yview
        )
        scroll_frame = tk.Frame(canvas)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        student_list = []
        if pdf_path and os.path.exists(pdf_path):
            records, _, _ = parse_scoresheet_pdf(pdf_path)
            student_list = sorted(records.keys())
        else:
            student_list = sorted(nicknames.keys())

        if not student_list:
            tk.Label(
                scroll_frame, text="Select a PDF in main window first."
            ).pack(pady=20)

        for name in student_list:
            row = tk.Frame(scroll_frame)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=name, width=25, anchor="w").pack(side="left")
            entry = tk.Entry(row, width=18)
            entry.insert(0, nicknames.get(name, ""))
            entry.pack(side="right", padx=5)
            self.entries[name] = entry

        tk.Button(self, text="Save Nicknames", command=self.save).pack(pady=10)

    def save(self):
        for name, entry in self.entries.items():
            val = entry.get().strip()
            if val:
                self.nicknames[name] = val
            elif name in self.nicknames:
                del self.nicknames[name]

        save_json(NICKNAMES_FILE, self.nicknames)
        messagebox.showinfo("Saved", "Nicknames updated successfully!")
        self.destroy()


class SettingsDialog(tk.Toplevel):

    def __init__(self, parent, config):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("500x200")
        self.resizable(False, False)
        self.config = config

        # Modal window configuration
        self.transient(parent)
        self.grab_set()

        tk.Label(self, text="Default Input PDF Directory:").pack(
            anchor="w", padx=10, pady=(10, 0)
        )
        self.pdf_dir_var = tk.StringVar(
            value=self.config.get("default_pdf_dir", "")
        )
        pdf_frame = tk.Frame(self)
        pdf_frame.pack(fill="x", padx=10, pady=2)
        tk.Entry(pdf_frame, textvariable=self.pdf_dir_var).pack(
            side="left", expand=True, fill="x"
        )
        tk.Button(
            pdf_frame, text="Browse...", command=self.browse_pdf_dir
        ).pack(side="right", padx=(5, 0))

        tk.Label(self, text="Default Output Folder:").pack(
            anchor="w", padx=10, pady=(10, 0)
        )
        self.out_dir_var = tk.StringVar(
            value=self.config.get("default_output_dir", "")
        )
        out_frame = tk.Frame(self)
        out_frame.pack(fill="x", padx=10, pady=2)
        tk.Entry(out_frame, textvariable=self.out_dir_var).pack(
            side="left", expand=True, fill="x"
        )
        tk.Button(
            out_frame, text="Browse...", command=self.browse_out_dir
        ).pack(side="right", padx=(5, 0))

        btn_frame = tk.Frame(self)
        btn_frame.pack(side="bottom", fill="x", pady=15)
        tk.Button(btn_frame, text="Save", command=self.save).pack(
            side="right", padx=10
        )
        tk.Button(btn_frame, text="Cancel", command=self.destroy).pack(
            side="right"
        )

    def browse_pdf_dir(self):
        dir_path = filedialog.askdirectory(
            title="Select Default Input Directory"
        )
        if dir_path:
            self.pdf_dir_var.set(dir_path)

    def browse_out_dir(self):
        dir_path = filedialog.askdirectory(
            title="Select Default Output Directory"
        )
        if dir_path:
            self.out_dir_var.set(dir_path)

    def save(self):
        self.config["default_pdf_dir"] = self.pdf_dir_var.get()
        self.config["default_output_dir"] = self.out_dir_var.get()
        save_json(CONFIG_FILE, self.config)
        messagebox.showinfo("Success", "Settings saved successfully!")
        self.destroy()


# ----------------------------------------------------------------------
# Main Application Window
# ----------------------------------------------------------------------
class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Scoresheet PDF Converter & Retake Slip Generator")
        self.geometry("620x560")
        self.resizable(False, False)

        self.config = load_json(
            CONFIG_FILE, {"default_pdf_dir": "", "default_output_dir": ""}
        )
        self.nicknames = load_json(NICKNAMES_FILE, {})

        # Window instances tracking for single-instance dialogs
        self.settings_dialog = None
        self.nicknames_dialog = None

        self.pdf_path_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(
            value=self.config.get("default_output_dir", "")
        )
        self.period_var = tk.StringVar(value="Auto")
        self.assignments = []

        top_frame = tk.Frame(self)
        top_frame.pack(fill="x", padx=10, pady=5)
        tk.Button(
            top_frame, text="✏ Nicknames", command=self.open_nicknames
        ).pack(side="left")
        tk.Button(
            top_frame, text="⚙ Settings", command=self.open_settings
        ).pack(side="right")

        tk.Label(self, text="1. Select Scoresheet PDF File:").pack(
            anchor="w", padx=10
        )
        pdf_frame = tk.Frame(self)
        pdf_frame.pack(fill="x", padx=10, pady=2)
        tk.Entry(
            pdf_frame, textvariable=self.pdf_path_var, state="readonly"
        ).pack(side="left", expand=True, fill="x")
        tk.Button(
            pdf_frame, text="Select PDF", command=self.select_pdf
        ).pack(side="right", padx=(5, 0))

        chk_frame = tk.LabelFrame(
            self, text="2. Checkpoint Pair Selection (Auto-Pairs A/B)"
        )
        chk_frame.pack(fill="x", padx=10, pady=10)

        tk.Label(chk_frame, text="Select Checkpoint:").pack(
            anchor="w", padx=5, pady=2
        )
        self.chk_listbox = tk.Listbox(
            chk_frame, selectmode="single", height=6, exportselection=False
        )
        self.chk_listbox.pack(fill="x", padx=5, pady=2)
        self.chk_listbox.bind("<<ListboxSelect>>", self.on_checkpoint_select)

        opts_frame = tk.Frame(self)
        opts_frame.pack(fill="x", padx=10, pady=5)

        tk.Label(opts_frame, text="Period:").grid(row=0, column=0, sticky="w")
        period_cb = ttk.Combobox(
            opts_frame,
            textvariable=self.period_var,
            values=["Auto", "1", "2", "3", "4"],
            width=8,
            state="readonly",
        )
        period_cb.grid(row=0, column=1, sticky="w", padx=5)

        tk.Label(self, text="3. Output Folder:").pack(
            anchor="w", padx=10, pady=(5, 0)
        )
        out_frame = tk.Frame(self)
        out_frame.pack(fill="x", padx=10, pady=2)
        tk.Entry(
            out_frame, textvariable=self.output_dir_var, state="readonly"
        ).pack(side="left", expand=True, fill="x")
        tk.Button(
            out_frame, text="Select Folder", command=self.select_output_dir
        ).pack(side="right", padx=(5, 0))

        self.progress_frame = tk.Frame(self)
        self.progress_frame.pack(fill="x", padx=10, pady=5)
        self.progress_bar = ttk.Progressbar(
            self.progress_frame, mode="indeterminate"
        )
        self.progress_label = tk.Label(
            self.progress_frame, text="", font=("Arial", 9)
        )

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)

        self.btn_csv = tk.Button(
            btn_frame,
            text="Convert to CSV",
            bg="#2196F3",
            fg="white",
            font=("Arial", 10, "bold"),
            command=self.convert_csv,
        )
        self.btn_csv.pack(side="left", padx=10)

        self.btn_slips = tk.Button(
            btn_frame,
            text="Generate Retake Slips PDF",
            bg="#4CAF50",
            fg="white",
            font=("Arial", 10, "bold"),
            command=self.generate_slips,
        )
        self.btn_slips.pack(side="left", padx=10)

    def open_settings(self):
        if self.settings_dialog is not None and self.settings_dialog.winfo_exists():
            self.settings_dialog.lift()
            self.settings_dialog.focus_force()
            return

        self.settings_dialog = SettingsDialog(self, self.config)
        self.wait_window(self.settings_dialog)
        self.settings_dialog = None

        if not self.output_dir_var.get():
            self.output_dir_var.set(self.config.get("default_output_dir", ""))

    def open_nicknames(self):
        if self.nicknames_dialog is not None and self.nicknames_dialog.winfo_exists():
            self.nicknames_dialog.lift()
            self.nicknames_dialog.focus_force()
            return

        self.nicknames_dialog = NicknameManagerDialog(
            self, self.pdf_path_var.get(), self.nicknames
        )
        self.wait_window(self.nicknames_dialog)
        self.nicknames_dialog = None

    def select_pdf(self):
        initial_dir = self.config.get("default_pdf_dir", "") or os.getcwd()
        file_path = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="Select Scoresheet PDF",
            filetypes=[("PDF Files", "*.pdf")],
        )
        if file_path:
            self.pdf_path_var.set(file_path)
            self.load_checkpoints()

    def select_output_dir(self):
        initial_dir = self.config.get("default_output_dir", "") or os.getcwd()
        dir_path = filedialog.askdirectory(
            initialdir=initial_dir, title="Select Output Folder"
        )
        if dir_path:
            self.output_dir_var.set(dir_path)

    def load_checkpoints(self):
        pdf_path = self.pdf_path_var.get()
        if not pdf_path:
            return

        _, self.assignments, auto_p = parse_scoresheet_pdf(pdf_path)
        if self.period_var.get() == "Auto":
            self.period_var.set(auto_p)

        self.chk_listbox.delete(0, tk.END)
        for assign in self.assignments:
            self.chk_listbox.insert(tk.END, assign)

    def on_checkpoint_select(self, event):
        selection = self.chk_listbox.curselection()
        if not selection:
            return

        selected_index = selection[0]
        selected_title = self.assignments[selected_index]

        paired_title = None
        if "1A" in selected_title:
            paired_title = selected_title.replace("1A", "1B")
        elif "1B" in selected_title:
            paired_title = selected_title.replace("1B", "1A")
        elif "2A" in selected_title:
            paired_title = selected_title.replace("2A", "2B")
        elif "2B" in selected_title:
            paired_title = selected_title.replace("2B", "2A")
        elif "3A" in selected_title:
            paired_title = selected_title.replace("3A", "3B")
        elif "3B" in selected_title:
            paired_title = selected_title.replace("3B", "3A")
        elif "4A" in selected_title:
            paired_title = selected_title.replace("4A", "4B")
        elif "4B" in selected_title:
            paired_title = selected_title.replace("4B", "4A")

        if paired_title and paired_title in self.assignments:
            paired_idx = self.assignments.index(paired_title)
            self.chk_listbox.selection_clear(0, tk.END)
            self.chk_listbox.selection_set(selected_index)
            self.chk_listbox.selection_set(paired_idx)

    def start_loading(self, message):
        self.progress_bar.pack(fill="x", pady=2)
        self.progress_bar.start(10)
        self.progress_label.config(text=message)
        self.progress_label.pack()
        self.btn_csv.config(state="disabled")
        self.btn_slips.config(state="disabled")

    def stop_loading(self):
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.progress_label.pack_forget()
        self.btn_csv.config(state="normal")
        self.btn_slips.config(state="normal")

    def convert_csv(self):
        pdf_path = self.pdf_path_var.get()
        out_dir = self.output_dir_var.get()

        if not pdf_path or not out_dir:
            messagebox.showwarning(
                "Warning", "Please select a PDF file and output folder."
            )
            return

        out_csv = os.path.join(
            out_dir,
            os.path.splitext(os.path.basename(pdf_path))[0]
            + "_converted.csv",
        )

        def worker():
            try:
                extract_scoresheet_to_csv(pdf_path, out_csv)
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Success", f"CSV Saved to:\n{out_csv}"
                    ),
                )
            except Exception as e:
                err_msg = str(e)
                self.after(
                    0,
                    lambda msg=err_msg: messagebox.showerror(
                        "Error", f"CSV Conversion Failed:\n{msg}"
                    ),
                )
            finally:
                self.after(0, self.stop_loading)

        self.start_loading("Parsing scoresheet and saving CSV...")
        threading.Thread(target=worker, daemon=True).start()

    def generate_slips(self):
        pdf_path = self.pdf_path_var.get()
        out_dir = self.output_dir_var.get()
        selected_indices = self.chk_listbox.curselection()

        if not pdf_path or not out_dir:
            messagebox.showwarning(
                "Warning", "Please select a PDF file and output folder."
            )
            return

        if len(selected_indices) < 2:
            messagebox.showwarning(
                "Warning", "Please select a checkpoint pair (A & B)."
            )
            return

        chk1 = self.assignments[selected_indices[0]]
        chk2 = self.assignments[selected_indices[1]]

        period = (
            None if self.period_var.get() == "Auto" else self.period_var.get()
        )
        out_pdf = os.path.join(
            out_dir,
            os.path.splitext(os.path.basename(pdf_path))[0]
            + "_retake_slips.pdf",
        )

        def worker():
            try:
                generate_latex_slips(
                    pdf_path, chk1, chk2, period, out_pdf, self.nicknames
                )
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Success", f"Retake Slips compiled to:\n{out_pdf}"
                    ),
                )
            except Exception as e:
                err_msg = str(e)
                self.after(
                    0,
                    lambda msg=err_msg: messagebox.showerror(
                        "Error", f"Generation Failed:\n{msg}"
                    ),
                )
            finally:
                self.after(0, self.stop_loading)

        self.start_loading("Compiling Retake Slips PDF...")
        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    app = App()
    app.mainloop()