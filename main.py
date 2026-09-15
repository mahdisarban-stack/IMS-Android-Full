import sqlite3
import shutil
from pathlib import Path
from datetime import datetime
import uuid

import flet as ft

try:
    import cv2
except Exception:
    cv2 = None

try:
    import numpy as np
except Exception:
    np = None

APP_DIR = Path(ft.app_storage_path() or Path.home() / ".ims_mobile")
APP_DIR.mkdir(parents=True, exist_ok=True)
DB = APP_DIR / "inventory.db"
SEED = Path(__file__).with_name("inventory_seed.db")


def db():
    if not DB.exists() and SEED.exists():
        shutil.copy2(SEED, DB)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def money(value):
    try:
        return f"{float(value):,.0f} تومان"
    except Exception:
        return "۰ تومان"


def jalali(gy, gm, gd):
    # Gregorian -> Jalali, no external package required.
    gdm = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + gdm[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def shamsi_now():
    d = datetime.now()
    y, m, day = jalali(d.year, d.month, d.day)
    return f"{y:04d}/{m:02d}/{day:02d} {d:%H:%M}"


def gregorian_to_jalali_text(text):
    if not text:
        return ""
    try:
        date_part = str(text).split()[0].replace("/", "-")
        y, m, d = [int(x) for x in date_part.split("-")[:3]]
        jy, jm, jd = jalali(y, m, d)
        time_part = " " + " ".join(str(text).split()[1:]) if len(str(text).split()) > 1 else ""
        return f"{jy:04d}/{jm:02d}/{jd:02d}{time_part}"
    except Exception:
        return str(text)


def decode_barcode(path):
    if cv2 is None or np is None:
        return ""
    try:
        image = cv2.imread(str(path))
        if image is None:
            return ""
        # QR first.
        qr = cv2.QRCodeDetector()
        value, _, _ = qr.detectAndDecode(image)
        if value:
            return value.strip()
        # OpenCV barcode module, when included in the Android build.
        if hasattr(cv2, "barcode") and hasattr(cv2.barcode, "BarcodeDetector"):
            detector = cv2.barcode.BarcodeDetector()
            if hasattr(detector, "detectAndDecodeWithType"):
                result = detector.detectAndDecodeWithType(image)
                if isinstance(result, tuple) and len(result) >= 2:
                    values = result[1]
                    if values:
                        for item in values:
                            if item:
                                return str(item).strip()
            if hasattr(detector, "detectAndDecode"):
                result = detector.detectAndDecode(image)
                values = result[0] if isinstance(result, tuple) else result
                if isinstance(values, (list, tuple)):
                    for item in values:
                        if item:
                            return str(item).strip()
                elif values:
                    return str(values).strip()
    except Exception:
        pass
    return ""


def main(page: ft.Page):
    page.title = "IMS | انبارداری موبایل"
    page.rtl = True
    page.padding = 12
    page.scroll = ft.ScrollMode.AUTO
    page.theme_mode = ft.ThemeMode.LIGHT

    status = ft.Text("آفلاین و آماده کار", color=ft.Colors.GREEN)
    content = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO)
    search_box = ft.TextField(label="جستجوی نام، کد یا بارکد")
    barcode_box = ft.TextField(label="بارکد یا کد کالا")
    selected = {"id": None}

    def refresh():
        page.update()

    def notify(text, color=None):
        status.value = text
        if color:
            status.color = color
        page.snack_bar = ft.SnackBar(ft.Text(text))
        page.snack_bar.open = True
        refresh()

    def query(sql, args=(), one=False):
        con = db()
        rows = con.execute(sql, args).fetchone() if one else con.execute(sql, args).fetchall()
        con.close()
        return rows

    def execute(sql, args=()):
        con = db()
        cur = con.execute(sql, args)
        con.commit()
        last = cur.lastrowid
        con.close()
        return last

    def home(_=None):
        p = query("select count(*) n from products", one=True)["n"]
        stock = query("select coalesce(sum(single_stock),0) s, coalesce(sum(carton_stock),0) c from products", one=True)
        low = query("select count(*) n from products where single_stock <= coalesce(min_stock,0) and coalesce(min_stock,0)>0", one=True)["n"]
        exp = query("select coalesce(sum(amount),0) a from expenses", one=True)["a"]
        value = query("select coalesce(sum(single_stock*sell_price + carton_stock*carton_count*sell_price),0) v from products", one=True)["v"]
        content.controls = [
            ft.Text("داشبورد", size=26, weight=ft.FontWeight.BOLD),
            ft.Card(ft.Container(ft.Column([
                ft.Text(f"تعداد کالا: {p}", size=19),
                ft.Text(f"موجودی تکی: {stock['s']}", size=19),
                ft.Text(f"موجودی کارتن: {stock['c']}", size=19),
                ft.Text(f"کالاهای کم‌موجودی: {low}", size=19),
                ft.Text(f"ارزش تقریبی موجودی: {money(value)}", size=19),
                ft.Text(f"جمع هزینه‌ها: {money(exp)}", size=19),
            ]), padding=16)),
            ft.Text(f"امروز: {shamsi_now()}", size=15),
            status,
        ]
        refresh()

    def products(_=None):
        term = search_box.value.strip()
        like = f"%{term}%"
        rows = query("select * from products where name like ? or code like ? or barcode like ? order by id desc", (like, like, like))
        controls = [ft.Text("کالاها", size=26, weight=ft.FontWeight.BOLD), ft.Row([search_box, ft.ElevatedButton("جستجو", on_click=products)]), ft.ElevatedButton("➕ ثبت کالای جدید", on_click=add_product)]
        if not rows:
            controls.append(ft.Text("کالایی پیدا نشد."))
        for p in rows:
            controls.append(ft.Card(ft.Container(ft.Column([
                ft.Text(p["name"] or "بدون نام", size=18, weight=ft.FontWeight.BOLD),
                ft.Text(f"کد: {p['code'] or '-'} | بارکد: {p['barcode'] or '-'}"),
                ft.Text(f"تکی: {p['single_stock']} | کارتن: {p['carton_stock']} | در کارتن: {p['carton_count']}"),
                ft.Text(f"خرید: {money(p['buy_price'])} | فروش: {money(p['sell_price'])}"),
                ft.Row([
                    ft.ElevatedButton("ویرایش", data=p["id"], on_click=edit_product),
                    ft.TextButton("حذف", data=p["id"], on_click=delete_product),
                ]),
            ]), padding=12)))
        content.controls = controls
        refresh()

    fields = {}
    for key, label, value in [
        ("name", "نام کالا", ""), ("code", "کد کالا", ""), ("barcode", "بارکد", ""),
        ("category", "دسته‌بندی", ""), ("brand", "برند", ""), ("color", "رنگ", ""),
        ("unit", "واحد", "عدد"), ("carton_count", "تعداد در کارتن", "1"),
        ("carton_stock", "موجودی کارتن", "0"), ("single_stock", "موجودی تکی", "0"),
        ("buy_price", "قیمت خرید", "0"), ("sell_price", "قیمت فروش", "0"),
        ("min_stock", "حداقل موجودی", "0"), ("location", "محل نگهداری", ""),
        ("description", "توضیحات", ""),
    ]:
        fields[key] = ft.TextField(label=label, value=value)

    def add_product(_=None):
        for k in fields:
            fields[k].value = "1" if k == "carton_count" else ("0" if k in {"carton_stock", "single_stock", "buy_price", "sell_price", "min_stock"} else ("عدد" if k == "unit" else ""))
        content.controls = [ft.Text("ثبت کالای جدید", size=26, weight=ft.FontWeight.BOLD)] + list(fields.values()) + [ft.ElevatedButton("ثبت کالا", on_click=save_product), ft.TextButton("بازگشت", on_click=products)]
        refresh()

    def save_product(_=None):
        try:
            vals = {k: fields[k].value.strip() for k in fields}
            if not vals["name"]:
                notify("نام کالا الزامی است.", ft.Colors.RED); return
            execute("insert into products(code,barcode,name,category,brand,color,unit,carton_count,carton_stock,single_stock,buy_price,sell_price,min_stock,location,description,image) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                vals["code"], vals["barcode"], vals["name"], vals["category"], vals["brand"], vals["color"], vals["unit"],
                int(vals["carton_count"] or 1), int(vals["carton_stock"] or 0), int(vals["single_stock"] or 0),
                float(vals["buy_price"] or 0), float(vals["sell_price"] or 0), int(vals["min_stock"] or 0), vals["location"], vals["description"], ""
            ))
            notify("کالا با موفقیت ثبت شد ✅", ft.Colors.GREEN); products()
        except Exception as exc:
            notify(f"خطا در ثبت کالا: {exc}", ft.Colors.RED)

    def edit_product(e):
        pid = int(e.control.data)
        p = query("select * from products where id=?", (pid,), one=True)
        if not p: return
        for k in fields:
            fields[k].value = str(p[k] if p[k] is not None else "")
        def update_product(_):
            try:
                vals = {k: fields[k].value.strip() for k in fields}
                execute("update products set code=?,barcode=?,name=?,category=?,brand=?,color=?,unit=?,carton_count=?,carton_stock=?,single_stock=?,buy_price=?,sell_price=?,min_stock=?,location=?,description=? where id=?", (
                    vals["code"], vals["barcode"], vals["name"], vals["category"], vals["brand"], vals["color"], vals["unit"],
                    int(vals["carton_count"] or 1), int(vals["carton_stock"] or 0), int(vals["single_stock"] or 0), float(vals["buy_price"] or 0), float(vals["sell_price"] or 0), int(vals["min_stock"] or 0), vals["location"], vals["description"], pid))
                notify("کالا ویرایش شد ✅", ft.Colors.GREEN); products()
            except Exception as exc: notify(f"خطا: {exc}", ft.Colors.RED)
        content.controls = [ft.Text("ویرایش کالا", size=26, weight=ft.FontWeight.BOLD)] + list(fields.values()) + [ft.ElevatedButton("ذخیره تغییرات", on_click=update_product), ft.TextButton("بازگشت", on_click=products)]
        refresh()

    def delete_product(e):
        pid = int(e.control.data)
        try:
            execute("delete from stock_movements where product_id=?", (pid,))
            execute("delete from products where id=?", (pid,))
            notify("کالا حذف شد.", ft.Colors.GREEN); products()
        except Exception as exc: notify(f"حذف ناموفق: {exc}", ft.Colors.RED)

    mv_code = ft.TextField(label="بارکد یا کد کالا")
    mv_type = ft.Dropdown(label="نوع عملیات", value="ورود", options=[ft.dropdown.Option("ورود"), ft.dropdown.Option("خروج")])
    mv_unit = ft.Dropdown(label="واحد", value="تکی", options=[ft.dropdown.Option("تکی"), ft.dropdown.Option("کارتن")])
    mv_qty = ft.TextField(label="تعداد", value="1")
    mv_price = ft.TextField(label="قیمت", value="0")
    mv_desc = ft.TextField(label="توضیحات")
    mv_info = ft.Text("کالایی انتخاب نشده")

    def find_movement(_=None):
        value = mv_code.value.strip()
        p = query("select * from products where barcode=? or code=? limit 1", (value, value), one=True)
        selected["id"] = p["id"] if p else None
        mv_info.value = f"{p['name']} | تکی {p['single_stock']} | کارتن {p['carton_stock']}" if p else "کالا پیدا نشد"
        refresh()

    def save_movement(_=None):
        if not selected["id"]:
            find_movement()
        if not selected["id"]: return
        try:
            qty = int(mv_qty.value or 0)
            price = float(mv_price.value or 0)
            con = db(); p = con.execute("select * from products where id=?", (selected["id"],)).fetchone()
            field = "single_stock" if mv_unit.value == "تکی" else "carton_stock"
            current = int(p[field] or 0)
            new_value = current + qty if mv_type.value == "ورود" else current - qty
            if qty <= 0 or new_value < 0:
                con.close(); notify("تعداد نامعتبر است یا موجودی کافی نیست.", ft.Colors.RED); return
            con.execute(f"update products set {field}=? where id=?", (new_value, p["id"]))
            con.execute("insert into stock_movements(product_id,movement_type,quantity,unit_type,price,movement_date,description) values(?,?,?,?,?,?,?)", (p["id"], mv_type.value, qty, mv_unit.value, price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), mv_desc.value))
            con.commit(); con.close(); mv_info.value = f"ثبت شد ✅ | موجودی جدید: {new_value}"; notify("عملیات ثبت شد.", ft.Colors.GREEN); refresh()
        except Exception as exc: notify(f"خطا: {exc}", ft.Colors.RED)

    def movement(_=None):
        content.controls = [ft.Text("ورود / خروج کالا", size=26, weight=ft.FontWeight.BOLD), ft.Row([mv_code, ft.ElevatedButton("جستجو", on_click=find_movement)]), mv_info, mv_type, mv_unit, mv_qty, mv_price, mv_desc, ft.ElevatedButton("ثبت عملیات", on_click=save_movement)]
        refresh()

    def history(_=None):
        rows = query("select m.*,p.name from stock_movements m join products p on p.id=m.product_id order by m.id desc limit 100")
        controls = [ft.Text("گردش کالا", size=26, weight=ft.FontWeight.BOLD)]
        for r in rows:
            controls.append(ft.Card(ft.Container(ft.Column([ft.Text(f"{r['name']} | {r['movement_type']} {r['quantity']} {r['unit_type']}", weight=ft.FontWeight.BOLD), ft.Text(f"تاریخ: {gregorian_to_jalali_text(r['movement_date'])} | قیمت: {money(r['price'])}"), ft.Text(r['description'] or "")]), padding=10)))
        content.controls = controls; refresh()

    def warehouses(_=None):
        rows = query("select * from warehouses order by id desc")
        name = ft.TextField(label="نام انبار")
        loc = ft.TextField(label="موقعیت")
        def save(_):
            if name.value.strip():
                try: execute("insert into warehouses(name,location,description) values(?,?,?)", (name.value.strip(), loc.value.strip(), "")); warehouses()
                except Exception as exc: notify(f"خطا: {exc}", ft.Colors.RED)
        content.controls=[ft.Text("انبارها",size=26,weight=ft.FontWeight.BOLD),name,loc,ft.ElevatedButton("ثبت انبار",on_click=save)] + [ft.ListTile(title=ft.Text(r["name"]),subtitle=ft.Text(r["location"] or "")) for r in rows]; refresh()

    def people(table, title, columns):
        rows = query(f"select * from {table} order by id desc")
        vals = {c: ft.TextField(label=lab) for c,lab in columns}
        def save(_):
            try:
                data=[vals[c].value.strip() for c,_ in columns]
                execute(f"insert into {table}({','.join(c for c,_ in columns)}) values({','.join('?' for _ in columns)})", data); people(table,title,columns)
            except Exception as exc: notify(f"خطا: {exc}",ft.Colors.RED)
        content.controls=[ft.Text(title,size=26,weight=ft.FontWeight.BOLD)]+list(vals.values())+[ft.ElevatedButton("ثبت",on_click=save)]+[ft.ListTile(title=ft.Text(" | ".join(str(r[c] or "") for c,_ in columns))) for r in rows]; refresh()

    def expenses(_=None):
        rows=query("select * from expenses order by id desc")
        title=ft.TextField(label="عنوان")
        cat=ft.TextField(label="دسته‌بندی")
        amount=ft.TextField(label="مبلغ",value="0")
        desc=ft.TextField(label="توضیحات")
        def save(_):
            try:
                now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"); execute("insert into expenses(expense_date,category,title,amount,description,created_at) values(?,?,?,?,?,?)",(now[:10],cat.value.strip(),title.value.strip(),float(amount.value or 0),desc.value.strip(),now)); expenses()
            except Exception as exc: notify(f"خطا: {exc}",ft.Colors.RED)
        controls=[ft.Text("هزینه‌ها",size=26,weight=ft.FontWeight.BOLD),title,cat,amount,desc,ft.ElevatedButton("ثبت هزینه",on_click=save)]
        for r in rows: controls.append(ft.Card(ft.Container(ft.Column([ft.Text(f"{r['title']} | {money(r['amount'])}",weight=ft.FontWeight.BOLD),ft.Text(f"{gregorian_to_jalali_text(r['expense_date'])} | {r['category']}"),ft.Text(r['description'] or "")]),padding=10)))
        content.controls=controls; refresh()

    file_picker = ft.FilePicker()
    page.overlay.append(file_picker)
    scan_status=ft.Text("برای بارکد، عکس را انتخاب کنید.")
    def picked(e: ft.FilePickerResultEvent):
        if not e.files: return
        path=e.files[0].path
        code=decode_barcode(path) if path else ""
        if code:
            mv_code.value=code; scan_status.value=f"بارکد: {code}"; find_movement()
        else:
            scan_status.value="بارکد خوانده نشد؛ عکس واضح‌تر انتخاب کنید یا بارکد را دستی وارد کنید."
        refresh()
    file_picker.on_result=picked
    def scanner(_=None):
        content.controls=[ft.Text("بارکدخوان",size=26,weight=ft.FontWeight.BOLD),ft.Text("برای جلوگیری از خطای دوربین، اسکن این نسخه از عکس بارکد انجام می‌شود. می‌توانید عکس را با دوربین گوشی بگیرید و سپس انتخاب کنید."),ft.ElevatedButton("📷 انتخاب عکس بارکد",on_click=lambda e:file_picker.pick_files(allow_multiple=False,allowed_extensions=["jpg","jpeg","png"])),scan_status,mv_code,ft.ElevatedButton("جستجو",on_click=find_movement),mv_info]; refresh()

    def reports(_=None):
        p=query("select count(*) n from products",one=True)["n"]; m=query("select count(*) n from stock_movements",one=True)["n"]; exp=query("select coalesce(sum(amount),0) a from expenses",one=True)["a"]
        content.controls=[ft.Text("گزارشات",size=26,weight=ft.FontWeight.BOLD),ft.Text(f"تعداد کالا: {p}"),ft.Text(f"تعداد عملیات: {m}"),ft.Text(f"جمع هزینه‌ها: {money(exp)}"),ft.Text(f"تاریخ گزارش: {shamsi_now()}")]; refresh()

    def nav(label):
        return {"خانه":home,"کالاها":products,"ثبت کالا":add_product,"ورود/خروج":movement,"بارکدخوان":scanner,"گردش کالا":history,"انبارها":warehouses,"مشتریان":lambda _:people("customers","مشتریان",[("name","نام"),("phone","تلفن"),("address","آدرس")]),"تامین‌کنندگان":lambda _:people("suppliers","تامین‌کنندگان",[("name","نام"),("phone","تلفن"),("company","شرکت")]),"هزینه‌ها":expenses,"گزارشات":reports}[label]

    buttons=["خانه","کالاها","ثبت کالا","ورود/خروج","بارکدخوان","گردش کالا","انبارها","مشتریان","تامین‌کنندگان","هزینه‌ها","گزارشات"]
    page.add(ft.Text("IMS موبایل",size=30,weight=ft.FontWeight.BOLD),ft.Text("نسخه کامل آفلاین",color=ft.Colors.BLUE),ft.Row([ft.ElevatedButton(x,data=x,on_click=lambda e:nav(x)(e)) for x in buttons],wrap=True),ft.Divider(),content)
    home()

if __name__ == "__main__":
    ft.run(main)
