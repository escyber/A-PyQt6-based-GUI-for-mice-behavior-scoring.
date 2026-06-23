import sys
import os
import csv
import cv2

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
    QLabel, QLineEdit, QComboBox, QDialog, QFormLayout, QAbstractItemView, QMessageBox
)
from PyQt6.QtGui import QImage, QPixmap, QKeyEvent

class DragDropTableWidget(QTableWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropOverwriteMode(False)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def dropEvent(self, event):
        if event.source() == self:
            rows = self.selectedItems()
            if not rows:
                return
            source_row = rows[0].row()
            
            target_row = self.indexAt(event.position().toPoint()).row()
            if target_row < 0:
                target_row = self.rowCount() - 1
                
            if source_row == target_row:
                event.accept()
                return

            row_data = []
            for col in range(self.columnCount()):
                item = self.item(source_row, col)
                row_data.append(item.text() if item else "")

            self.insertRow(target_row)
            if source_row > target_row:
                source_row += 1
                
            for col, text in enumerate(row_data):
                self.setItem(target_row, col, QTableWidgetItem(text))
                
            self.removeRow(source_row)
            event.accept()
        else:
            super().dropEvent(event)


class AddBehaviorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Behavior Shortcut")
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self)
        self.name_input = QLineEdit()
        self.key_input = QLineEdit()
        self.key_input.setMaxLength(1)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["State", "Point"])
        self.desc_input = QLineEdit()

        layout.addRow("Behavior Name:", self.name_input)
        layout.addRow("Shortcut Key:", self.key_input)
        layout.addRow("Event Type:", self.type_combo)
        layout.addRow("Description:", self.desc_input)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def get_data(self):
        return (
            self.name_input.text().strip(),
            self.key_input.text().strip().upper(),
            self.type_combo.currentText(),
            self.desc_input.text().strip()
        )


class BehaviorScorer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EthoLog - Precision Behavior Scorer")
        self.setGeometry(100, 100, 1200, 750)

        self.cap = None
        self.fps = 25.0
        self.total_frames = 0
        self.current_frame = 0
        self.video_duration = 0.0
        self.is_playing = False
        self.video_path = ""

        self.ethogram = {}       
        self.active_states = {}  

        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)

        self.init_ui()
        self.load_default_ethogram()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        sidebar_layout = QVBoxLayout()
        sidebar_layout.addWidget(QLabel("<b>Ethogram Configuration</b>"))
        
        # Changed columns to 4 to accommodate Description right after Type
        self.ethogram_table = QTableWidget(0, 4)
        self.ethogram_table.setHorizontalHeaderLabels(["Key", "Behavior", "Type", "Description"])
        self.ethogram_table.horizontalHeader().setStretchLastSection(True)
        self.ethogram_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ethogram_table.itemChanged.connect(self.handle_ethogram_cell_edited)
        sidebar_layout.addWidget(self.ethogram_table)

        etho_btn_layout = QHBoxLayout()
        add_etho_btn = QPushButton("Add Behavior")
        add_etho_btn.clicked.connect(self.add_behavior_dialog)
        load_csv_btn = QPushButton("Load Configuration")
        load_csv_btn.clicked.connect(self.load_ethogram_csv)
        etho_btn_layout.addWidget(add_etho_btn)
        load_csv_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        add_etho_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        etho_btn_layout.addWidget(load_csv_btn)
        sidebar_layout.addLayout(etho_btn_layout)

        motion_btn = QPushButton("Run Motion Pre-Scoring")
        motion_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        motion_btn.clicked.connect(self.run_motion_prescoring)
        sidebar_layout.addWidget(motion_btn)

        content_layout = QVBoxLayout()
        
        self.video_frame_label = QLabel("Click 'Open Video File' to load tracking stream.")
        self.video_frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_frame_label.setStyleSheet("background-color: black; color: white; min-height: 400px;")
        content_layout.addWidget(self.video_frame_label)

        self.timeline_label = QLabel("Frame: 0/0  |  Time: 0.000 / 0.000 s")
        content_layout.addWidget(self.timeline_label)

        media_btn_layout = QHBoxLayout()
        open_video_btn = QPushButton("Open Video File")
        open_video_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        open_video_btn.clicked.connect(self.open_video)
        media_btn_layout.addWidget(open_video_btn)
        content_layout.addLayout(media_btn_layout)

        content_layout.addWidget(QLabel("<b>Event Log Table (Drag and Drop Rows to Order)</b>"))
        self.log_table = DragDropTableWidget(0, 16)
        
        self.johan_headers = [
            "Observation id", "Observation date", "Description", "Observation duration",
            "Observation type", "Time offset (s)", "Media duration (s)", "FPS",
            "Subject", "Behavior", "Behavioral category", "Behavior type",
            "Time", "Image index", "Image file path", "Comment"
        ]
        self.log_table.setHorizontalHeaderLabels(self.johan_headers)
        content_layout.addWidget(self.log_table)

        table_ops_layout = QHBoxLayout()
        add_row_btn = QPushButton("Add Manual Row")
        add_row_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        add_row_btn.clicked.connect(self.add_manual_row)
        
        del_row_btn = QPushButton("Delete Selected Row")
        del_row_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        del_row_btn.clicked.connect(self.delete_selected_row)
        
        export_tsv_btn = QPushButton("Export Log")
        export_tsv_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        export_tsv_btn.clicked.connect(self.export_to_tsv)
        
        table_ops_layout.addWidget(add_row_btn)
        table_ops_layout.addWidget(del_row_btn)
        table_ops_layout.addWidget(export_tsv_btn)
        content_layout.addLayout(table_ops_layout)

        main_layout.addLayout(sidebar_layout, 1)
        main_layout.addLayout(content_layout, 3)

        main_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        main_widget.setFocus()

    def load_default_ethogram(self):
        self.ethogram_table.blockSignals(True)
        defaults = [
            ("E", "Exploration", "State", "Exploring environment"), 
            ("D", "Digging", "State", "Displacing bedding material"), 
            ("G", "Body grooming", "State", "Cleaning fur or face"), 
            ("R", "Rearing", "Point", "Standing on hind limbs")
        ]
        for key, name, b_type, desc in defaults:
            self.register_behavior(key, name, b_type, desc)
        self.ethogram_table.blockSignals(False)

    def register_behavior(self, key, name, b_type, desc=""):
        clean_key = str(key).strip().upper()
        self.ethogram[clean_key] = (name, b_type, desc)
        row = self.ethogram_table.rowCount()
        self.ethogram_table.insertRow(row)
        self.ethogram_table.setItem(row, 0, QTableWidgetItem(clean_key))
        self.ethogram_table.setItem(row, 1, QTableWidgetItem(name))
        self.ethogram_table.setItem(row, 2, QTableWidgetItem(b_type))
        self.ethogram_table.setItem(row, 3, QTableWidgetItem(desc))

    def handle_ethogram_cell_edited(self, item):
        self.ethogram_table.blockSignals(True)
        new_dict = {}
        for row in range(self.ethogram_table.rowCount()):
            k_item = self.ethogram_table.item(row, 0)
            n_item = self.ethogram_table.item(row, 1)
            t_item = self.ethogram_table.item(row, 2)
            d_item = self.ethogram_table.item(row, 3)
            
            if k_item and n_item and t_item:
                k_str = k_item.text().strip().upper()
                n_str = n_item.text().strip()
                t_str = t_item.text().strip()
                d_str = d_item.text().strip() if d_item else ""
                if k_str and n_str:
                    k_item.setText(k_str)
                    new_dict[k_str] = (n_str, t_str, d_str)
        self.ethogram = new_dict
        self.ethogram_table.blockSignals(False)

    def add_behavior_dialog(self):
        dial = AddBehaviorDialog(self)
        if dial.exec() == QDialog.DialogCode.Accepted:
            name, key, b_type, desc = dial.get_data()
            if key and name:
                self.ethogram_table.blockSignals(True)
                self.register_behavior(key, name, b_type, desc)
                self.ethogram_table.blockSignals(False)
        self.centralWidget().setFocus()

    def load_ethogram_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Ethogram CSV", "", "CSV Files (*.csv);;Text (*.txt)")
        if path:
            self.ethogram_table.blockSignals(True)
            self.ethogram.clear()
            self.ethogram_table.setRowCount(0)
            with open(path, mode='r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 3:
                        key = row[0].strip().upper()
                        name = row[1].strip()
                        b_type = row[2].strip()
                        desc = row[3].strip() if len(row) >= 4 else ""
                        self.register_behavior(key, name, b_type, desc)
            self.ethogram_table.blockSignals(False)
        self.centralWidget().setFocus()

    def open_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Mouse Video File", "", "Videos (*.mp4 *.avi)")
        if path:
            self.video_path = path
            self.cap = cv2.VideoCapture(path)
            self.fps = self.cap.get(cv2.CAP_PROP_FPS)
            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.video_duration = self.total_frames / self.fps
            self.current_frame = 0
            self.update_video_frame()
        self.centralWidget().setFocus()

    def update_video_frame(self):
        if self.cap:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
            ret, frame = self.cap.read()
            if ret:
                frame = cv2.resize(frame, (640, 480))
                rgb_img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_img.shape
                bytes_per_line = ch * w
                
                q_img = QImage(rgb_img.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                self.video_frame_label.setPixmap(QPixmap.fromImage(q_img))
                
                current_time = self.current_frame / self.fps
                self.timeline_label.setText(
                    f"Frame: {self.current_frame}/{self.total_frames}  |  "
                    f"Time: {current_time:.3f} / {self.video_duration:.3f} s"
                )

    def next_frame(self):
        if self.current_frame < self.total_frames - 1:
            self.current_frame += 1
            self.update_video_frame()
        else:
            self.timer.stop()
            self.is_playing = False

    def keyPressEvent(self, event: QKeyEvent):
        v_key = event.key()
        
        if v_key == Qt.Key.Key_Space:
            if self.is_playing:
                self.timer.stop()
                self.is_playing = False
            else:
                self.timer.start(int(1000 / self.fps))
                self.is_playing = True
            return
            
        elif v_key == Qt.Key.Key_Left:
            if self.current_frame > 0:
                self.current_frame -= 1
                self.update_video_frame()
            return
            
        elif v_key == Qt.Key.Key_Right:
            if self.current_frame < self.total_frames - 1:
                self.current_frame += 1
                self.update_video_frame()
            return

        key_text = event.text().upper().strip()
        if not key_text:
            if Qt.Key.Key_0 <= v_key <= Qt.Key.Key_9:
                key_text = str(v_key - Qt.Key.Key_0)

        if key_text in self.ethogram:
            # Unpack name, event type, and description
            b_name, b_type, b_desc = self.ethogram[key_text]
            current_time = self.current_frame / self.fps
            
            if b_type == "Point":
                self.append_log_row(b_name, "POINT", current_time, b_desc)
            else:
                if b_name in self.active_states:
                    self.append_log_row(b_name, "STOP", current_time, b_desc)
                    del self.active_states[b_name]
                else:
                    self.append_log_row(b_name, "START", current_time, b_desc)
                    self.active_states[b_name] = current_time

    def append_log_row(self, behavior_name, type_flag, event_time, description=""):
        row = self.log_table.rowCount()
        self.log_table.insertRow(row)

        obs_id = os.path.basename(self.video_path) if self.video_path else "top.mp4"
        
        fields = {
            "Observation id": obs_id,
            "Description": description if description else "NA",
            "Observation duration": f"{self.video_duration:.3f}",
            "Observation type": "Media file(s)",
            "Time offset (s)": "0",
            "Media duration (s)": f"{self.video_duration:.3f}",
            "FPS": f"{self.fps:.3f}",
            "Behavior": behavior_name,
            "Behavior type": type_flag,
            "Time": f"{event_time:.3f}",
            "Image index": str(self.current_frame),
            "Comment": "NA"
        }

        for col_name, val in fields.items():
            col_idx = self.johan_headers.index(col_name)
            self.log_table.setItem(row, col_idx, QTableWidgetItem(val))

    def add_manual_row(self):
        row = self.log_table.rowCount()
        self.log_table.insertRow(row)
        current_time = self.current_frame / self.fps
        
        self.log_table.setItem(row, self.johan_headers.index("Observation id"), QTableWidgetItem("top.mp4"))
        self.log_table.setItem(row, self.johan_headers.index("Behavior type"), QTableWidgetItem("START"))
        self.log_table.setItem(row, self.johan_headers.index("Time"), QTableWidgetItem(f"{current_time:.3f}"))

    def delete_selected_row(self):
        selected = self.log_table.currentRow()
        if selected >= 0:
            self.log_table.removeRow(selected)

    def run_motion_prescoring(self):
        if not self.video_path:
            QMessageBox.warning(self, "No Video Loaded", "Please open a video before running motion analysis.")
            return

        temp_cap = cv2.VideoCapture(self.video_path)
        ret, prev_frame = temp_cap.read()
        if not ret:
            return

        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        frame_idx = 1
        state_active = False

        while True:
            ret, frame = temp_cap.read()
            if not ret:
                break
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(gray, prev_gray)
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            non_zero = cv2.countNonZero(thresh)
            
            is_moving = non_zero > 3000
            current_time = frame_idx / self.fps

            if is_moving and not state_active:
                self.append_log_row("Active", "START", current_time)
                state_active = True
            elif not is_moving and state_active:
                self.append_log_row("Active", "STOP", current_time)
                state_active = False

            prev_gray = gray
            frame_idx += 1

        temp_cap.release()
        QMessageBox.information(self, "Analysis Complete", "Motion pre-scoring completed.")
        self.centralWidget().setFocus()

    def export_to_tsv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Tracking Log", "", "TSV Files (*.tsv);;CSV Files (*.csv)")
        if path:
            delimiter = "\t" if path.endswith('.tsv') else ","
            with open(path, mode='w', newline='') as f:
                writer = csv.writer(f, delimiter=delimiter)
                writer.writerow(self.johan_headers)
                
                for row in range(self.log_table.rowCount()):
                    row_data = []
                    for col in range(self.log_table.columnCount()):
                        item = self.log_table.item(row, col)
                        row_data.append(item.text() if item else "")
                    writer.writerow(row_data)
            QMessageBox.information(self, "Export Successful", "Log file saved successfully.")
        self.centralWidget().setFocus()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BehaviorScorer()
    window.show()
    sys.exit(app.exec())
