import sys
import sqlite3
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QMessageBox, QDialog, QFormLayout, QLineEdit,
    QComboBox, QDateEdit, QTextEdit, QToolBar,
    QHeaderView, QGroupBox
)
from PyQt6.QtGui import QAction, QPixmap, QIcon
from PyQt6.QtCore import Qt, QDate

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas


DB = "finance_journal.db"


class Database:
    def __init__(self, path=DB):
        self.path = path
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        cur = self.conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL CHECK(kind IN ('expense','income')))")
        cur.execute("CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, dt TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('expense','income')), amount REAL NOT NULL, category_id INTEGER, description TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')), FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE SET NULL)")
        self.conn.commit()
        self._create_defaults()

    def _create_defaults(self):
        cur = self.conn.cursor()
        defaults = [("Продукты", "expense"), ("Кафе и рестораны", "expense"), ("Транспорт", "expense"), ("Развлечения", "expense"), ("Зарплата", "income"), ("Подарки", "income"), ("Проценты/Дивиденды", "income")]
        for n, k in defaults:
            cur.execute("INSERT OR IGNORE INTO categories (name, kind) VALUES (?, ?)", (n, k))
        self.conn.commit()

    def get_cats(self, kind=None):
        cur = self.conn.cursor()
        if kind in ("expense", "income"):
            cur.execute("SELECT * FROM categories WHERE kind=? ORDER BY name", (kind,))
        else:
            cur.execute("SELECT * FROM categories ORDER BY kind, name")
        return cur.fetchall()

    def add_cat(self, name, kind):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO categories (name, kind) VALUES (?, ?)", (name, kind))
        self.conn.commit()

    def edit_cat(self, cid, name, kind):
        cur = self.conn.cursor()
        cur.execute("UPDATE categories SET name=?, kind=? WHERE id=?", (name, kind, cid))
        self.conn.commit()

    def del_cat(self, cid):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM categories WHERE id=?", (cid,))
        self.conn.commit()

    def add_tx(self, dt, kind, amount, cat_id, desc):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO transactions (dt, kind, amount, category_id, description) VALUES (?, ?, ?, ?, ?)",
            (dt, kind, float(amount), cat_id, desc)
        )
        self.conn.commit()

    def edit_tx(self, tx_id, dt, kind, amount, cat_id, desc):
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE transactions SET dt=?, kind=?, amount=?, category_id=?, description=? WHERE id=?",
            (dt, kind, float(amount), cat_id, desc, tx_id)
        )
        self.conn.commit()

    def del_tx(self, tx_id):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
        self.conn.commit()

    def find_tx(self, start=None, end=None, category=None, kind=None, text=None):
        cur = self.conn.cursor()
        q = "SELECT t.*, c.name as category_name FROM transactions t LEFT JOIN categories c ON c.id=t.category_id WHERE 1=1"
        p = []

        if start:
            q += " AND dt >= ?"
            p.append(start)
        if end:
            q += " AND dt <= ?"
            p.append(end)
        if category:
            q += " AND category_id = ?"
            p.append(category)
        if kind in ("expense", "income"):
            q += " AND t.kind = ?"
            p.append(kind)
        if text:
            q += " AND (description LIKE ? OR c.name LIKE ?)"
            p.append(f"%{text}%")
            p.append(f"%{text}%")

        q += " ORDER BY dt DESC, id DESC"
        cur.execute(q, p)
        return cur.fetchall()

    def get_balance(self, start=None, end=None):
        cur = self.conn.cursor()
        q = "SELECT dt, SUM(CASE WHEN kind='income' THEN amount ELSE -amount END) as delta FROM transactions WHERE 1=1"
        p = []
        if start:
            q += " AND dt >= ?"
            p.append(start)
        if end:
            q += " AND dt <= ?"
            p.append(end)
        q += " GROUP BY dt ORDER BY dt"
        cur.execute(q, p)

        rows = cur.fetchall()
        res = []
        total = Decimal('0')
        for r in rows:
            total += Decimal(str(r['delta'] or 0))
            res.append((r['dt'], float(total)))
        return res

    def cat_sums(self, start=None, end=None, kind=None):
        cur = self.conn.cursor()
        q = "SELECT c.name as category_name, SUM(t.amount) as total FROM transactions t JOIN categories c ON c.id=t.category_id WHERE 1=1"
        p = []
        if start:
            q += " AND dt >= ?"
            p.append(start)
        if end:
            q += " AND dt <= ?"
            p.append(end)
        if kind in ("expense", "income"):
            q += " AND t.kind = ?"
            p.append(kind)
        q += " GROUP BY c.id ORDER BY total DESC"
        cur.execute(q, p)
        return cur.fetchall()


def to_iso(qd: QDate):
    d = date(qd.year(), qd.month(), qd.day())
    return d.isoformat()


def from_iso(s: str):
    y, m, d = map(int, s.split("-"))
    return QDate(y, m, d)


def fmt_money(x):
    try:
        d = Decimal(x)
    except:
        d = Decimal('0')
    return f"{d:.2f}"


def make_pix(c, sz=(32, 32)):
    p = QPixmap(sz[0], sz[1])
    p.fill(c)
    return p


class EditTransactionWindow(QDialog):
    def __init__(self, db: Database, parent=None, data=None):
        super().__init__(parent)
        self.db = db
        self.data = data
        self.setWindowTitle("Транзакция" if data is None else "Редактирование")
        self.resize(400, 240)

        layout = QVBoxLayout()
        form = QFormLayout()

        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDate(QDate.currentDate())

        self.type = QComboBox()
        self.type.addItems(["expense", "income"])

        self.amount = QLineEdit()

        self.cat = QComboBox()
        self._cats()

        self.desc = QTextEdit()
        self.desc.setFixedHeight(60)

        form.addRow("Дата:", self.date)
        form.addRow("Тип:", self.type)
        form.addRow("Сумма:", self.amount)
        form.addRow("Категория:", self.cat)
        form.addRow("Описание:", self.desc)

        layout.addLayout(form)

        btns = QHBoxLayout()
        self.ok = QPushButton("Сохранить")
        self.cancel = QPushButton("Отмена")
        btns.addStretch()
        btns.addWidget(self.ok)
        btns.addWidget(self.cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

        self.ok.clicked.connect(self.accept)
        self.cancel.clicked.connect(self.reject)
        self.type.currentTextChanged.connect(self._cats)

        if data:
            self.date.setDate(from_iso(data['dt']))
            self.type.setCurrentText(data['kind'])
            self.amount.setText(fmt_money(data['amount']))
            cid = data['category_id']
            if cid:
                for i in range(self.cat.count()):
                    if self.cat.itemData(i) == cid:
                        self.cat.setCurrentIndex(i)
                        break
            self.desc.setPlainText(data['description'] or "")

    def _cats(self):
        self.cat.clear()
        k = self.type.currentText()
        cats = self.db.get_cats(kind=k)
        for c in cats:
            self.cat.addItem(c['name'], c['id'])

    def get_info(self):
        dt = to_iso(self.date.date())
        kind = self.type.currentText()
        raw = self.amount.text().strip().replace(",", ".")
        try:
            money = Decimal(raw)
        except InvalidOperation:
            raise ValueError("Неверный формат суммы")
        if money <= 0:
            raise ValueError("Сумма должна быть положительной")
        cat = self.cat.currentData()
        desc = self.desc.toPlainText().strip()
        return dt, kind, money, cat, desc


class CategoryWindow(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Категории")
        self.resize(500, 300)

        layout = QVBoxLayout()
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "Название", "Тип"])
        self.table.setColumnHidden(0, True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        form = QFormLayout()
        self.name = QLineEdit()
        self.kind = QComboBox()
        self.kind.addItems(["expense", "income"])
        form.addRow("Название:", self.name)
        form.addRow("Тип:", self.kind)
        layout.addLayout(form)

        btns = QHBoxLayout()
        self.add = QPushButton("Добавить")
        self.edit = QPushButton("Изменить")
        self.delbtn = QPushButton("Удалить")
        btns.addWidget(self.add)
        btns.addWidget(self.edit)
        btns.addWidget(self.delbtn)
        btns.addStretch()
        layout.addLayout(btns)
        self.setLayout(layout)

        self.add.clicked.connect(self.add_cat)
        self.edit.clicked.connect(self.edit_cat)
        self.delbtn.clicked.connect(self.del_cat)
        self.table.itemSelectionChanged.connect(self.on_select)
        self.load()

    def load(self):
        self.table.setRowCount(0)
        cats = self.db.get_cats()
        for c in cats:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(c['id'])))
            self.table.setItem(r, 1, QTableWidgetItem(c['name']))
            self.table.setItem(r, 2, QTableWidgetItem(c['kind']))
        self.table.resizeRowsToContents()

    def add_cat(self):
        n = self.name.text().strip()
        k = self.kind.currentText()
        if not n:
            QMessageBox.warning(self, "Ошибка", "Название не может быть пустым")
            return
        try:
            self.db.add_cat(n, k)
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Ошибка", "Такая категория уже существует")
        self.load()

    def on_select(self):
        sel = self.table.selectedItems()
        if sel:
            r = sel[0].row()
            self.name.setText(self.table.item(r, 1).text())
            self.kind.setCurrentText(self.table.item(r, 2).text())

    def edit_cat(self):
        sel = self.table.selectedItems()
        if not sel:
            QMessageBox.information(self, "Инфо", "Выберите категорию")
            return
        r = sel[0].row()
        cid = int(self.table.item(r, 0).text())
        n = self.name.text().strip()
        k = self.kind.currentText()
        if not n:
            QMessageBox.warning(self, "Ошибка", "Название не может быть пустым")
            return
        try:
            self.db.edit_cat(cid, n, k)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", str(e))
        self.load()

    def del_cat(self):
        sel = self.table.selectedItems()
        if not sel:
            QMessageBox.information(self, "Инфо", "Выберите категорию")
            return
        r = sel[0].row()
        cid = int(self.table.item(r, 0).text())
        ask = QMessageBox.question(self, "Удалить?", "Удалить категорию? Транзакции будут без категории.",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ask == QMessageBox.StandardButton.Yes:
            self.db.del_cat(cid)
            self.load()


class ReportWindow(QDialog):
    def __init__(self, db: Database, parent=None, start=None, end=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Отчёты")
        self.resize(900, 600)

        main = QVBoxLayout()
        top = QHBoxLayout()

        self.start = QDateEdit()
        self.start.setCalendarPopup(True)
        self.end = QDateEdit()
        self.end.setCalendarPopup(True)
        self.start.setDate(QDate.currentDate().addMonths(-1))
        self.end.setDate(QDate.currentDate())

        if start:
            self.start.setDate(from_iso(start))
        if end:
            self.end.setDate(from_iso(end))

        self.kind = QComboBox()
        self.kind.addItems(["all", "expense", "income"])
        self.refresh = QPushButton("Обновить")

        top.addWidget(QLabel("С:"))
        top.addWidget(self.start)
        top.addWidget(QLabel("По:"))
        top.addWidget(self.end)
        top.addWidget(QLabel("Тип:"))
        top.addWidget(self.kind)
        top.addWidget(self.refresh)
        top.addStretch()
        main.addLayout(top)

        self.fig = Figure(figsize=(8, 6))
        self.canvas = FigureCanvas(self.fig)
        main.addWidget(self.canvas)
        self.setLayout(main)

        self.refresh.clicked.connect(self.draw)
        self.draw()

    def draw(self):
        self.fig.clear()
        s = to_iso(self.start.date())
        e = to_iso(self.end.date())
        k = self.kind.currentText()
        if k == "all":
            k = None

        ax1 = self.fig.add_subplot(2, 1, 1)
        data = self.db.cat_sums(start=s, end=e, kind=k)
        names = [r['category_name'] for r in data]
        vals = [r['total'] for r in data]

        if names:
            ax1.bar(names, vals)
            ax1.set_title("По категориям")
            ax1.tick_params(axis='x', rotation=45)
        else:
            ax1.text(0.5, 0.5, "Нет данных", ha='center')

        ax2 = self.fig.add_subplot(2, 1, 2)
        bal = self.db.get_balance(s, e)
        if bal:
            xs = [datetime.fromisoformat(d[0]).date() for d in bal]
            ys = [d[1] for d in bal]
            ax2.plot(xs, ys, marker='o')
            ax2.set_title("Баланс")
        else:
            ax2.text(0.5, 0.5, "Нет данных", ha='center')

        self.fig.tight_layout()
        self.canvas.draw()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.setWindowTitle("Debtify")
        self.setWindowIcon(QIcon("finanse.ico"))
        self.resize(1000, 600)
        self._ui()
        self.refresh()

    def _ui(self):
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)

        btn_add = QAction("Добавить", self)
        btn_edit = QAction("Изменить", self)
        btn_del = QAction("Удалить", self)
        btn_cats = QAction("Категории", self)
        btn_reports = QAction("Графики", self)
        btn_refresh = QAction("Обновить", self)
        btn_about = QAction("О программе", self)

        toolbar.addAction(btn_add)
        toolbar.addAction(btn_edit)
        toolbar.addAction(btn_del)
        toolbar.addSeparator()
        toolbar.addAction(btn_cats)
        toolbar.addAction(btn_reports)
        toolbar.addAction(btn_refresh)
        toolbar.addSeparator()
        toolbar.addAction(btn_about)

        btn_add.triggered.connect(self.add_tx)
        btn_edit.triggered.connect(self.edit_tx)
        btn_del.triggered.connect(self.delete_tx)
        btn_cats.triggered.connect(self.open_categories)
        btn_reports.triggered.connect(self.open_reports)
        btn_refresh.triggered.connect(self.refresh)
        btn_about.triggered.connect(self.show_about)

        center = QWidget()
        main = QVBoxLayout()

        fbox = QGroupBox("Фильтры")
        fl = QHBoxLayout()

        self.fs = QDateEdit()
        self.fs.setCalendarPopup(True)
        self.fs.setDate(QDate.currentDate().addMonths(-1))
        self.fe = QDateEdit()
        self.fe.setCalendarPopup(True)
        self.fe.setDate(QDate.currentDate())
        self.fk = QComboBox()
        self.fk.addItems(["all", "expense", "income"])
        self.fc = QComboBox()
        self._upd_cat()
        self.fsr = QLineEdit()
        self.fsr.setPlaceholderText("Поиск...")
        self.apply = QPushButton("Применить")
        self.clear = QPushButton("Сбросить")

        fl.addWidget(QLabel("С:"))
        fl.addWidget(self.fs)
        fl.addWidget(QLabel("По:"))
        fl.addWidget(self.fe)
        fl.addWidget(QLabel("Тип:"))
        fl.addWidget(self.fk)
        fl.addWidget(QLabel("Категория:"))
        fl.addWidget(self.fc)
        fl.addWidget(self.fsr)
        fl.addWidget(self.apply)
        fl.addWidget(self.clear)

        fbox.setLayout(fl)
        main.addWidget(fbox)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Дата", "Тип", "Сумма", "Категория", "Описание"])
        self.table.setColumnHidden(0, True)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        main.addWidget(self.table)

        totals = QHBoxLayout()
        self.total_lbl = QLabel("Баланс: 0.00")
        self.inc_lbl = QLabel("Доходы: 0.00")
        self.exp_lbl = QLabel("Расходы: 0.00")
        totals.addWidget(self.total_lbl)
        totals.addStretch()
        totals.addWidget(self.inc_lbl)
        totals.addWidget(self.exp_lbl)
        main.addLayout(totals)
        center.setLayout(main)
        self.setCentralWidget(center)

        self.apply.clicked.connect(self.refresh)
        self.clear.clicked.connect(self.clear_filters)
        self.table.itemDoubleClicked.connect(self.edit_tx)

    def _upd_cat(self):
        self.fc.clear()
        self.fc.addItem("Все", None)
        for cat in self.db.get_cats():
            self.fc.addItem(f"{cat['name']} ({cat['kind']})", cat['id'])

    def clear_filters(self):
        self.fs.setDate(QDate.currentDate().addMonths(-1))
        self.fe.setDate(QDate.currentDate())
        self.fk.setCurrentText("all")
        self.fc.setCurrentIndex(0)
        self.fsr.clear()
        self.refresh()

    def refresh(self):
        s = to_iso(self.fs.date())
        e = to_iso(self.fe.date())
        cat = self.fc.currentData()
        k = self.fk.currentText()
        if k == "all":
            k = None
        text = self.fsr.text().strip() or None

        recs = self.db.find_tx(s, e, cat, k, text)
        self.table.setRowCount(0)

        total = Decimal('0')
        inc = Decimal('0')
        exp = Decimal('0')

        for r in recs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(r['id'])))
            self.table.setItem(row, 1, QTableWidgetItem(r['dt']))
            self.table.setItem(row, 2, QTableWidgetItem(r['kind']))
            self.table.setItem(row, 3, QTableWidgetItem(fmt_money(r['amount'])))
            self.table.setItem(row, 4, QTableWidgetItem(r['category_name'] or ""))
            self.table.setItem(row, 5, QTableWidgetItem(r['description'] or ""))

            val = Decimal(str(r['amount']))
            if r['kind'] == "income":
                total += val
                inc += val
            else:
                total -= val
                exp += val

        self.total_lbl.setText(f"Баланс: {fmt_money(total)}")
        self.inc_lbl.setText(f"Доходы: {fmt_money(inc)}")
        self.exp_lbl.setText(f"Расходы: {fmt_money(exp)}")

    def add_tx(self):
        dlg = EditTransactionWindow(self.db, self)
        dlg.date.setDate(self.fe.date())
        if dlg.exec():
            try:
                dt, kind, money, cat, desc = dlg.get_info()
                self.db.add_tx(dt, kind, money, cat, desc)
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", str(e))
            self._upd_cat()
            self.refresh()

    def edit_tx(self):
        sel = self.table.selectedItems()
        if not sel:
            QMessageBox.information(self, "Инфо", "Выберите запись")
            return
        row = sel[0].row()
        tx_id = int(self.table.item(row, 0).text())

        cur = self.db.conn.cursor()
        cur.execute("SELECT * FROM transactions WHERE id=?", (tx_id,))
        data = cur.fetchone()
        if not data:
            QMessageBox.warning(self, "Ошибка", "Транзакция не найдена")
            self.refresh()
            return

        dlg = EditTransactionWindow(self.db, self, data)
        if dlg.exec():
            try:
                dt, kind, money, cat, desc = dlg.get_info()
                self.db.edit_tx(tx_id, dt, kind, money, cat, desc)
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", str(e))
            self._upd_cat()
            self.refresh()

    def delete_tx(self):
        sel = self.table.selectedItems()
        if not sel:
            QMessageBox.information(self, "Инфо", "Выберите запись")
            return
        row = sel[0].row()
        tx_id = int(self.table.item(row, 0).text())

        ask = QMessageBox.question(self, "Удалить?", "Удалить транзакцию?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ask == QMessageBox.StandardButton.Yes:
            try:
                self.db.del_tx(tx_id)
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", str(e))
            self.refresh()

    def open_categories(self):
        dlg = CategoryWindow(self.db, self)
        dlg.exec()
        self._upd_cat()

    def open_reports(self):
        s = to_iso(self.fs.date())
        e = to_iso(self.fe.date())
        dlg = ReportWindow(self.db, self, s, e)
        dlg.exec()

    def show_about(self):
        pix = QPixmap("finanse.png")
        msg = QMessageBox(self)
        msg.setWindowTitle("О программе")
        if not pix.isNull():
            pix = pix.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            msg.setIconPixmap(pix)
        msg.setText("Debtify\nАвтор: Егор Волков\n2025")
        msg.exec()


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("finanse.ico"))
    app.setApplicationName("Debtify")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
