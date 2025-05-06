# room.py  –  flexible 4‑way video + chat window
# ----------------------------------------------
from PyQt5 import QtCore, QtGui, QtWidgets
import pathlib, os
ROOT = pathlib.Path(__file__).resolve().parent           # V2 or gui
IMG  = lambda n: os.fspath(ROOT / ("imgs" if ROOT.name == "gui" else "gui/imgs") / n)


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setWindowTitle("Room")
        MainWindow.resize(1400, 900)
        MainWindow.setStyleSheet("background:#7851A9;")

        # ===== central widget & root vertical layout =========================
        self.centralwidget = QtWidgets.QWidget(MainWindow)
        root = QtWidgets.QVBoxLayout(self.centralwidget)
        root.setContentsMargins(20, 10, 20, 10)
        root.setSpacing(10)

        # --------------------------------------------------------------------
        #  HEADER  (logo — spacer — room‑id — spacer — buttons)
        # --------------------------------------------------------------------
        header = QtWidgets.QHBoxLayout()
        root.addLayout(header)

        self.logo = QtWidgets.QLabel()
        self.logo.setMinimumSize(120, 30)
        self.logo.setPixmap(QtGui.QPixmap(IMG("logo no bg.png")))
        self.logo.setScaledContents(True)
        header.addWidget(self.logo)

        header.addStretch(1)

        self.label = QtWidgets.QLabel("ROOM ID:")
        self.label.setFont(QtGui.QFont("Cascadia Code SemiBold", 24,
                                       QtGui.QFont.Bold))
        self.label.setStyleSheet("color:#FFF;")
        header.addWidget(self.label, 0, QtCore.Qt.AlignCenter)

        header.addStretch(2)

        # common button policy
        sz_pol = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                       QtWidgets.QSizePolicy.Expanding)

        self.cameraButton = QtWidgets.QPushButton()
        self.cameraButton.setSizePolicy(sz_pol)
        self.cameraButton.setIcon(QtGui.QIcon(IMG("camera_green.png")))
        self.cameraButton.setIconSize(QtCore.QSize(80, 80))
        self.cameraButton.setFlat(True)
        header.addWidget(self.cameraButton)

        self.micButton = QtWidgets.QPushButton()
        self.micButton.setSizePolicy(sz_pol)
        self.micButton.setIcon(QtGui.QIcon(IMG("mic_green.png")))
        self.micButton.setIconSize(QtCore.QSize(80, 80))
        self.micButton.setFlat(True)
        header.addWidget(self.micButton)

        self.SettingsButton = QtWidgets.QPushButton("Settings")
        self.SettingsButton.setFont(QtGui.QFont("Cascadia Mono SemiLight", 24))
        self.SettingsButton.setStyleSheet(
            "QPushButton{background:#FFF;color:#5A3D85;border:2px solid #C8A2C8;"
            "border-radius:12px;padding:8px 20px;}"
            "QPushButton:hover{background:#F8F1FF;border-color:#A175A7;}"
            "QPushButton:pressed{background:#E6D4F0;border-color:#7D4F9F;}")
        header.addWidget(self.SettingsButton)

        # ── NEW: Leave button ─────────────────────────────────────────────
        self.leaveButton = QtWidgets.QPushButton("Leave")
        self.leaveButton.setFont(QtGui.QFont("Cascadia Mono SemiLight", 24))
        self.leaveButton.setStyleSheet(
                "QPushButton{background:#FFB3B3;color:#7D0A0A;border:2px solid #F08080;"
                "border-radius:12px;padding:8px 20px;}"
                "QPushButton:hover{background:#FFC9C9;border-color:#E05757;}"
                "QPushButton:pressed{background:#E6A0A0;border-color:#B33A3A;}")
        header.addWidget(self.leaveButton)

        # --------------------------------------------------------------------
        #  SPLITTER  (video grid  |  chat column)
        # --------------------------------------------------------------------
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        root.addWidget(splitter, 1)          # stretch = take all remaining

        # -- LEFT  : 2×2 video grid -----------------------------------------
        video = QtWidgets.QWidget()
        grid  = QtWidgets.QGridLayout(video)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        self.graphicsView_1  = QtWidgets.QGraphicsView(); grid.addWidget(self.graphicsView_1, 0, 0)
        self.graphicsView_2  = QtWidgets.QGraphicsView(); grid.addWidget(self.graphicsView_2, 0, 1)
        self.graphicsView_3  = QtWidgets.QGraphicsView(); grid.addWidget(self.graphicsView_3, 1, 0)
        self.graphicsView_4 = QtWidgets.QGraphicsView(); grid.addWidget(self.graphicsView_4, 1, 1)

        PLACEHOLDER_STYLE = (
            "background:#4C2C76;"  # a darker purple than the page
            "border:2px solid #AAA;"
            "border-radius:6px;"
        )

        MUTE_ICON = QtGui.QPixmap(IMG("mic_red_small20.png")).scaled(
                20, 20, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)

        # every video cell expands & keeps a minimum size
        for gv in (self.graphicsView_1, self.graphicsView_2,
                   self.graphicsView_3, self.graphicsView_4):
                gv.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                 QtWidgets.QSizePolicy.Expanding)
                gv.setMinimumSize(150, 120)
                gv.setFrameShape(QtWidgets.QFrame.NoFrame)  # remove border
                gv.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                gv.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)  # ← make it visible

        for i, gv in enumerate((self.graphicsView_1, self.graphicsView_2,
                                self.graphicsView_3, self.graphicsView_4), start=0):
                lbl = QtWidgets.QLabel(video)
                lbl.setStyleSheet("color:white;font:18px 'Cascadia Code';"
                                  "background:rgba(0,0,0,40%);padding:2px;")
                lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom)
                lbl.hide()  # <‑ start invisible
                lbl.raise_()  # above graphics view
                setattr(self, f"nameLabel{i}", lbl)

                badge = QtWidgets.QLabel(video)
                badge.setPixmap(MUTE_ICON)
                badge.hide();
                badge.raise_()
                setattr(self, f"muteBadge{i}", badge)

        # tell Qt each row / column should take equal share
        for i in range(2):
            grid.setRowStretch(i, 1)
            grid.setColumnStretch(i, 1)

        splitter.addWidget(video)

        # -- RIGHT : chat ----------------------------------------------------
        chat = QtWidgets.QWidget()
        chat_v = QtWidgets.QVBoxLayout(chat)
        chat_v.setContentsMargins(0, 0, 0, 0)
        chat_v.setSpacing(8)

        self.textBrowser = QtWidgets.QTextBrowser()
        self.textBrowser.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                       QtWidgets.QSizePolicy.Expanding)
        chat_v.addWidget(self.textBrowser)

        self.messageBox = QtWidgets.QTextEdit()
        self.messageBox.setFixedHeight(80)
        chat_v.addWidget(self.messageBox)

        self.sendButton = QtWidgets.QPushButton("Send")
        self.sendButton.setFont(QtGui.QFont("Cascadia Mono SemiLight", 24))
        self.sendButton.setSizePolicy(QtWidgets.QSizePolicy.Minimum,
                                      QtWidgets.QSizePolicy.Fixed)
        self.sendButton.setStyleSheet(
            "QPushButton{background:#E6E6FA;color:#5A3D85;border:2px solid #C8A2C8;"
            "border-radius:12px;padding:8px 20px;}"
            "QPushButton:hover{background:#F8F1FF;border-color:#A175A7;}"
            "QPushButton:pressed{background:#E6D4F0;border-color:#7D4F9F;}")
        chat_v.addWidget(self.sendButton)

        splitter.addWidget(chat)
        splitter.setStretchFactor(0, 3)   # video gets ~75%
        splitter.setStretchFactor(1, 1)

        # --------------------------------------------------------------------
        MainWindow.setCentralWidget(self.centralwidget)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)


# small wrapper so client.py can `from room import MainWindow as RoomUI`
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)


# quick manual test
if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(); win.show()
    sys.exit(app.exec_())
