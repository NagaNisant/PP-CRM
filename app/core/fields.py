"""
fields.py - field types used in every module.py.

A Field knows how to: read itself from a form, validate/clean the value, show
it on screen and write it to Excel. To add a new kind of input (say, a
currency-aware amount) add one class here.
"""
import re
from flask import current_app
from .util import parse_date, fmt_date, fmt_money


class FieldError(ValueError):
    pass


class Field:
    kind = "text"
    sql_type = "TEXT"

    def __init__(self, name, label=None, *, required=False, default=None, help="", placeholder="",
                 section=None, stored=True, list=None, form=True, filter=None, export=None,
                 roles=None, unique=False, suggest=None, summary=False, badge=False,
                 hidden=False, max_length=None, attrs=None):
        self.name = name
        self.label = label or name.replace("_", " ").replace(" id", "").title()
        self.required, self.default, self.help, self.placeholder = required, default, help, placeholder
        self.section, self.stored, self.unique = section, stored, unique
        self.roles = roles                       # who may edit this field (None = anyone who may edit the record)
        self.suggest = suggest                   # dict(url=..., fills={'form_field': 'json_key'}) -> autocomplete
        self.summary, self.badge, self.max_length = summary, badge, max_length
        self.attrs = attrs or {}
        self.hidden = hidden
        self.show_in_form = False if hidden else form
        self.show_in_list = False if hidden else (stored if list is None else list)
        self.filterable = False if hidden else (stored if filter is None else filter)
        self.export = False if hidden else (stored if export is None else export)
        self.show_in_detail = not hidden

    # ----- form ----------------------------------------------------------
    def read(self, form, files=None, prefix=""):
        return (form.get(prefix + self.name) or "").strip()

    def clean(self, raw):
        if raw in (None, ""):
            return None
        if self.max_length and len(raw) > self.max_length:
            raise FieldError("Maximum %d characters" % self.max_length)
        return raw

    def to_form(self, value):
        return "" if value is None else str(value)

    # ----- output --------------------------------------------------------
    def display(self, value):
        return "" if value is None else str(value)

    def excel(self, value):
        return value

    def is_empty(self, value):
        return value in (None, "")


class Text(Field):
    pass


class TextArea(Field):
    kind = "textarea"


class Email(Field):
    kind = "email"

    def clean(self, raw):
        raw = super().clean(raw)
        if raw and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", raw):
            raise FieldError("Enter a valid e-mail address")
        return raw.lower() if raw else raw


class Phone(Field):
    kind = "phone"

    def clean(self, raw):
        raw = super().clean(raw)
        if raw and (not re.match(r"^[0-9+\-\s()/,]+$", raw) or len(re.sub(r"\D", "", raw)) < 6):
            raise FieldError("Enter a valid phone number")
        return raw


class Int(Field):
    kind = "int"
    sql_type = "INTEGER"

    def __init__(self, *a, min=None, max=None, **kw):
        super().__init__(*a, **kw)
        self.min, self.max = min, max

    def clean(self, raw):
        if raw in (None, ""):
            return None
        try:
            v = int(float(str(raw).replace(",", "")))
        except ValueError:
            raise FieldError("Enter a whole number")
        if self.min is not None and v < self.min:
            raise FieldError("Must be at least %s" % self.min)
        if self.max is not None and v > self.max:
            raise FieldError("Must be at most %s" % self.max)
        return v

    def display(self, value):
        return "" if value is None else str(value)


class Money(Field):
    kind = "money"
    sql_type = "REAL"

    def __init__(self, *a, min=None, **kw):
        super().__init__(*a, **kw)
        self.min = min

    def clean(self, raw):
        if raw in (None, ""):
            return None
        try:
            v = round(float(str(raw).replace(",", "")), 2)
        except ValueError:
            raise FieldError("Enter a number")
        if self.min is not None and v < self.min:
            raise FieldError("Must be at least %s" % self.min)
        return v

    def to_form(self, value):
        return "" if value is None else ("%g" % value if float(value).is_integer() else "%.2f" % value)

    def display(self, value):
        return fmt_money(value)


class Date(Field):
    kind = "date"

    def clean(self, raw):
        if raw in (None, ""):
            return None
        d = parse_date(raw)
        if not d:
            raise FieldError("Enter a valid date")
        return d.isoformat()

    def display(self, value):
        return fmt_date(value, current_app.config["DATE_DISPLAY"])

    def excel(self, value):
        return parse_date(value) if value else None


class Choice(Field):
    kind = "choice"

    def __init__(self, name, label=None, *, choices=(), **kw):
        super().__init__(name, label, **kw)
        self._choices = choices

    @property
    def choices(self):
        raw = self._choices() if callable(self._choices) else self._choices
        return [c if isinstance(c, (tuple, list)) else (c, c) for c in raw]

    def clean(self, raw):
        if raw in (None, ""):
            return None
        if raw not in [v for v, _ in self.choices]:
            raise FieldError("Choose one of the listed options")
        return raw

    def display(self, value):
        return dict(self.choices).get(value, value or "")


class MultiChoice(Choice):
    kind = "multichoice"

    def read(self, form, files=None, prefix=""):
        return ",".join(form.getlist(prefix + self.name))

    def clean(self, raw):
        if not raw:
            return None
        valid = [v for v, _ in self.choices]
        if any(x not in valid for x in raw.split(",")):
            raise FieldError("Invalid selection")
        return raw

    def display(self, value):
        return (value or "").replace(",", ", ")


class Bool(Field):
    kind = "bool"
    sql_type = "INTEGER"

    def read(self, form, files=None, prefix=""):
        return "1" if form.get(prefix + self.name) else "0"

    def clean(self, raw):
        return 1 if raw == "1" else 0

    def to_form(self, value):
        return "1" if value else ""

    def display(self, value):
        return "Yes" if value else "No"

    def is_empty(self, value):
        return False


class Ref(Field):
    """Foreign key to another module. `where` limits the dropdown (SQL on alias t)."""
    kind = "ref"
    sql_type = "INTEGER"

    def __init__(self, name, label=None, *, module, where=None, params=(), **kw):
        super().__init__(name, label, **kw)
        self.module, self.where, self.params = module, where, params

    def clean(self, raw):
        if raw in (None, ""):
            return None
        try:
            return int(raw)
        except ValueError:
            raise FieldError("Invalid selection")

    def options(self):
        from . import registry
        return registry.get(self.module).options(self.where, self.params)


class File(Field):
    kind = "file"

    def __init__(self, *a, accept=(".pdf",), **kw):
        super().__init__(*a, **kw)
        self.accept = tuple(accept)
        self.filterable = False

    def read(self, form, files=None, prefix=""):
        f = (files or {}).get(prefix + self.name)
        return f if f is not None and f.filename else None

    def clean(self, raw):
        if raw is None:
            return None
        from .uploads import allowed
        if not allowed(raw.filename, self.accept):
            raise FieldError("Allowed file types: " + ", ".join(self.accept))
        return raw

    def display(self, value):
        return "Attached" if value else ""


class Password(Field):
    kind = "password"

    def clean(self, raw):
        if raw and len(raw) < 8:
            raise FieldError("Use at least 8 characters")
        return raw or None


class Computed(Field):
    """Read-only column calculated in SQL (alias `t` = the main table). Filterable & sortable."""
    def __init__(self, name, label=None, *, sql, value="text", choices=(), **kw):
        kw.setdefault("stored", False)
        super().__init__(name, label, **kw)
        self.sql, self.kind = sql, value
        self.show_in_form = False
        self.filterable = kw.get("filter", True)
        self.export = kw.get("export", True)
        self.computed = True
        self._fmt = {"text": Text, "money": Money, "int": Int, "date": Date}.get(value)
        self._fmt = Choice(name, choices=choices) if value == "choice" else self._fmt(name)

    @property
    def choices(self):
        return self._fmt.choices

    def display(self, value):
        return self._fmt.display(value)

    def excel(self, value):
        return self._fmt.excel(value)
