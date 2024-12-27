import sys
from PyQt5.QtCore import *
from PyQt5.QtGui  import *
from PyQt5.QtWidgets import *
from FS import FileSystem
import os

def to_humain_readable(size: int):
    """Convert bytes to humain readable format"""
    for unit in ['o', 'Ko', 'Mo', 'Go', 'To']:
        if size < 1024.0:
            break
        size /= 1024.0
    return f"{size:.2f} {unit}"

class FSExplorerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Super FileSystem Explorer")
        self.fs = None
        self.LoginUI()

    def LoginUI(self):#login
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.password_label = QLabel("Enter password:")
        self.layout.addWidget(self.password_label)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.layout.addWidget(self.password)

        self.pin_label = QLabel("Enter pin:")
        self.layout.addWidget(self.pin_label)
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.Password)
        self.pin.keyPressEvent = self.login_press_event
        self.layout.addWidget(self.pin)

        self.login_btn = QPushButton("Login")
        self.login_btn.clicked.connect(self.login)
        self.layout.addWidget(self.login_btn)

    def login_press_event(self, e):
        if e.key() == Qt.Key_Return:
            return self.login()
        return QLineEdit.keyPressEvent(self.pin, e)

    def initUI(self):#file + btn to create / delete
        self.file_list = QListWidget()
        self.layout.addWidget(self.file_list)
        self.file_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.on_right_click)

        self.create_file_btn = QPushButton("Create file")
        self.create_file_btn.clicked.connect(self.create_file_wizard)
        self.layout.addWidget(self.create_file_btn)

        self.delete_file_btn = QPushButton("Delete file")
        self.delete_file_btn.clicked.connect(self.delete_file)
        self.layout.addWidget(self.delete_file_btn)


    def login(self):
        password = self.password.text()
        pin = self.pin.text()
        self.fs = FileSystem(0, password, pin)
        print("[*] Key generated"," "*20)
        self.initUI()
        #delete password and pin
        self.password_label.deleteLater()
        self.password.deleteLater()
        self.pin_label.deleteLater()
        self.pin.deleteLater()
        self.login_btn.deleteLater()
        self.list_files()

    def list_files(self):
        if not self.fs:
            print("Filesystem not initialized!")
            return
        self.file_list.clear()
        for fname in self.fs.directory:
            item = QListWidgetItem(f"{fname} {to_humain_readable(self.fs.directory[fname].size)}")
            self.file_list.addItem(item)

    def on_right_click(self,pos):
        item = self.file_list.itemAt(pos)
        if item:
            menu = QMenu()
            #set as selected
            self.file_list.setCurrentItem(item)
            menu.addAction("Download").triggered.connect(self.download_file)
            menu.addAction("Delete").triggered.connect(self.delete_file)
            menu.addAction("Rename").triggered.connect(self.rename_file)
            menu.exec_(self.file_list.mapToGlobal(pos))

    def download_file(self):
        if not self.fs:
            print("Filesystem not initialized!")
            return
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            print("No file selected!")
            return
        output_dir = QFileDialog.getExistingDirectory(self, "Select a directory to save files")
        if not output_dir:
            print("No output directory selected!")
            return
        for item in selected_items:
            file_name = item.text().split(" ")[0]
            with open(os.path.join(output_dir, file_name), "wb") as f:
                for chunk in self.fs.read_file(file_name):
                    #remove trailing \x00
                    chunk = chunk.rstrip(b"\x00")
                    f.write(chunk)
                f.close()
            print(f"File {file_name} downloaded!")

    def rename_file(self):
        if not self.fs:
            print("Filesystem not initialized!")
            return
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            print("No file selected!")
            return
        for item in selected_items:
            print(item.text())
            file_name = item.text().split(" ")[0]
            file_size = " ".join(item.text().split(" ")[1:])
            new_name, ok = QInputDialog.getText(self, "File rename", "Enter new file name:")
            if ok and new_name:
                self.fs.rename_file(file_name, new_name)
                item.setText(f"{new_name} {file_size}")

    def create_file_wizard(self):
        if not self.fs:
            print("Filesystem not initialized!")
            return
        file_name, ok = QInputDialog.getText(self, "File creation", "Enter file name:")
        if ok and file_name and " " not in file_name:
            file_path, _ = QFileDialog.getOpenFileName(self, "Select a source file")
            if file_path:
                self.create_file(file_name, file_path)
        elif " " in file_name:
            print("File name cannot contain spaces!")

    def create_file(self, file_name, file_path):
        if not self.fs:
            print("Filesystem not initialized!")
            return
        print(f"Creating file: {file_name} from {file_path}")
        fsize = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            if self.fs.create_file(file_name, f.read()):
                print(f"File {file_name} created!")
        self.file_list.addItem(f"{file_name} {to_humain_readable(fsize)}")

    def delete_file(self):
        if not self.fs:
            print("Filesystem not initialized!")
            return
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            print("No file selected!")
            return
        for item in selected_items:
            file_name = item.text().split(" ")[0]
            if self.fs.delete_file(file_name):
                print(f"File {file_name} deleted!")
            self.file_list.takeItem(self.file_list.row(item))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FSExplorerGUI()
    window.show()
    sys.exit(app.exec_())