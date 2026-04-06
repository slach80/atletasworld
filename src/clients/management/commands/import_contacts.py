"""
Management command: import_contacts
Parses all APC event/program CSV files from docs/clients/ and loads them
into ContactParent + ContactPlayer tables. Safe to run multiple times —
deduplicates on email and skips existing records.

Usage:
    python manage.py import_contacts
    python manage.py import_contacts --dry-run
    python manage.py import_contacts --clear  # wipe and reimport
"""
import csv
import re
from pathlib import Path
from django.core.management.base import BaseCommand
from django.utils import timezone
from clients.models import ContactParent, ContactPlayer


DOCS_DIR = Path(__file__).resolve().parents[4] / 'docs' / 'clients'

SOURCE_MAP = {
    '2nd S&P camp - list.csv':                                       'sp_camp',
    'APC Summer Program (Risposte) - Risposte del modulo 1.csv':     'apc_summer_2025',
    'AW Summer 2025 (Risposte) - Risposte del modulo 1.csv':         'aw_summer_2025',
    'Future Footballers Camp July 27th (Risposte) - Risposte del modulo 1.csv': 'ff_camp_jul_2024',
    'Future Footballers Camp June 22-23 - Sheet1.csv':               'ff_camp_jun_2024',
    'Future Footballers Camp June 22-23 2024 (Risposte) - Risposte del modulo 1.csv': 'ff_camp_jun_2024',
    'Future Footballers Program - Risposte del modulo 1.csv':        'ff_program',
    'NKC Spring Break Clinic (Risposte) - Risposte del modulo 1.csv':'nkc_spring_2025',
    'Winter Clinic December 27 (Responses) - Form Responses 1.csv':  'winter_2024',
}


def _clean(s):
    return (s or '').strip().strip('"').strip()


def _phone(p):
    if not p:
        return ''
    d = re.sub(r'\D', '', p)
    if len(d) == 10:
        return f'({d[:3]}) {d[3:6]}-{d[6:]}'
    if len(d) == 11 and d[0] == '1':
        return f'({d[1:4]}) {d[4:7]}-{d[7:]}'
    return p.strip()


def _dob(raw):
    """Return (dob_display, birth_year_int_or_None)"""
    raw = _clean(raw)
    if not raw:
        return '', None
    # pure 4-digit year
    if re.match(r'^(199\d|200\d|201\d|202\d)$', raw):
        return '', int(raw)
    # dd/mm/yyyy (Italian Google Forms)
    m = re.match(r'^(\d{1,2})/(\d{1,2})/((?:19|20)\d{2})$', raw)
    if m:
        return f'{m.group(2)}/{m.group(1)}/{m.group(3)}', int(m.group(3))
    # mm/dd/yyyy
    m = re.match(r'^(\d{1,2})[/.-](\d{1,2})[/.-]((?:19|20)\d{2})$', raw)
    if m:
        return f'{m.group(1)}/{m.group(2)}/{m.group(3)}', int(m.group(3))
    # look for year embedded in free text
    m = re.search(r'\b(199\d|200\d|201\d|202\d)\b', raw)
    if m:
        return raw, int(m.group(1))
    return raw, None


def _sex(s):
    s = _clean(s).lower()
    if s in ('male', 'm', 'boy'):
        return 'M'
    if s in ('female', 'f', 'girl'):
        return 'F'
    return ''


def _strip_suffix(name):
    """Remove ' S&P1', ' M', etc. suffixes from names."""
    return re.sub(r'\s+(S&P\d*|[MS]\d?)$', '', name.strip())


def _make_parent(email, phone, first='', last='', source='other'):
    email = (email or '').lower().strip()
    phone = _phone(phone)
    if not email and not phone:
        return None, False
    obj, created = ContactParent.objects.get_or_create(
        email=email,
        defaults=dict(phone=phone, first_name=first, last_name=last, source=source),
    )
    # Update phone if we got a better one
    if not obj.phone and phone:
        obj.phone = phone
        obj.save(update_fields=['phone'])
    return obj, created


def _make_player(parent, first, last, dob_raw, sex, team, pos, tshirt, source, notes=''):
    if not first:
        return None, False
    first = _strip_suffix(first)
    last  = _strip_suffix(last)
    dob_disp, birth_year = _dob(dob_raw)
    sex = _sex(sex)
    # Dedup within parent: same first+last+birth_year
    existing = parent.players.filter(
        first_name__iexact=first,
        last_name__iexact=last,
    ).first()
    if existing:
        return existing, False
    player = ContactPlayer.objects.create(
        parent=parent, first_name=first, last_name=last,
        dob=dob_disp, birth_year=birth_year, sex=sex,
        club_team=_clean(team)[:150], position=_clean(pos)[:100],
        tshirt_size=_clean(tshirt)[:10], source=source, notes=notes,
    )
    return player, True


class Command(BaseCommand):
    help = 'Import APC client contacts from CSV files in docs/clients/'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--clear',   action='store_true', help='Delete all contacts first')

    def handle(self, *args, **options):
        dry  = options['dry_run']
        verb = self.style.SUCCESS

        if options['clear'] and not dry:
            deleted = ContactParent.objects.all().delete()
            self.stdout.write(self.style.WARNING(f'Cleared: {deleted}'))

        parents_new = parents_skip = players_new = players_skip = 0

        def add_player(parent, fn, ln, dob_raw, sex, team, pos, tshirt, src, notes=''):
            nonlocal players_new, players_skip
            if dry:
                if fn:
                    players_new += 1
                return
            _, created = _make_player(parent, fn, ln, dob_raw, sex, team, pos, tshirt, src, notes)
            if created:
                players_new += 1
            else:
                players_skip += 1

        def add_parent(email, phone, first='', last='', source='other'):
            nonlocal parents_new, parents_skip
            if dry:
                parents_new += 1
                return None
            p, created = _make_parent(email, phone, first, last, source)
            if created:
                parents_new += 1
            else:
                parents_skip += 1
            return p

        # ── 1. S&P Camp ────────────────────────────────────────────────────
        f = DOCS_DIR / '2nd S&P camp - list.csv'
        if f.exists():
            with open(f, encoding='utf-8-sig', errors='replace') as fh:
                for row in csv.DictReader(fh):
                    fn = _clean(row.get('First Name', ''))
                    ln = _clean(row.get('Last Name', ''))
                    if not fn and not ln:
                        continue
                    parent = add_parent(row.get('Email', ''), row.get('Phone', ''), source='sp_camp')
                    if parent:
                        add_player(parent, fn, ln, '', '', '', '', '', 'sp_camp')

        # ── 2. APC Summer 2025 ────────────────────────────────────────────
        f = DOCS_DIR / 'APC Summer Program (Risposte) - Risposte del modulo 1.csv'
        if f.exists():
            with open(f, encoding='utf-8-sig', errors='replace') as fh:
                for row in csv.DictReader(fh):
                    fn = _clean(row.get('First name', ''))
                    ln = _clean(row.get('Last Name', ''))
                    if not fn and not ln:
                        continue
                    parent = add_parent(row.get('Email', ''), row.get('Phone Number', ''), source='apc_summer_2025')
                    if parent:
                        add_player(parent, fn, ln, row.get('DOB', ''),
                                   row.get('Sex', ''), row.get('Current Team (Full Name)', ''),
                                   row.get('Favorite Position', ''), '', 'apc_summer_2025')

        # ── 3. AW Summer 2025 ─────────────────────────────────────────────
        f = DOCS_DIR / 'AW Summer 2025 (Risposte) - Risposte del modulo 1.csv'
        if f.exists():
            with open(f, encoding='utf-8-sig', errors='replace') as fh:
                for row in csv.DictReader(fh):
                    fn = _clean(row.get('First name', ''))
                    ln = _clean(row.get('Last name', ''))
                    if not fn and not ln:
                        continue
                    parent = add_parent(row.get('E-mail', ''), row.get('Phone Number', ''), source='aw_summer_2025')
                    if parent:
                        add_player(parent, fn, ln, row.get('DOB', ''),
                                   row.get('Sex', ''), row.get('Current Team (Full Name)', ''),
                                   row.get('Favorite Position', ''), '', 'aw_summer_2025')

        # ── 4. FF Camp July 2024 ──────────────────────────────────────────
        f = DOCS_DIR / 'Future Footballers Camp July 27th (Risposte) - Risposte del modulo 1.csv'
        if f.exists():
            with open(f, encoding='utf-8-sig', errors='replace') as fh:
                reader = csv.reader(fh)
                rows = list(reader)
                hdrs = [h.strip().lower() for h in rows[1]] if len(rows) > 1 else []
                def gc(row, *keys):
                    for k in keys:
                        for i, h in enumerate(hdrs):
                            if k in h and i < len(row) and _clean(row[i]):
                                return _clean(row[i])
                    return ''
                for row in rows[2:]:
                    if not row or not any(row):
                        continue
                    fn = gc(row, 'first name'); ln = gc(row, 'last name')
                    if not fn:
                        continue
                    parent = add_parent(gc(row, 'email', 'e-mail'), gc(row, 'phone', 'mobile'), source='ff_camp_jul_2024')
                    if parent:
                        add_player(parent, fn, ln, gc(row, 'dob', 'birth'),
                                   gc(row, 'sex', 'gender'), gc(row, 'team', 'club'),
                                   gc(row, 'position'), gc(row, 't-shirt', 'tshirt', 'shirt'),
                                   'ff_camp_jul_2024')

        # ── 5. FF Camp June 22-23 (combined DOB field) ───────────────────
        f = DOCS_DIR / 'Future Footballers Camp June 22-23 - Sheet1.csv'
        if f.exists():
            with open(f, encoding='utf-8-sig', errors='replace') as fh:
                for row in csv.reader(fh):
                    if not row or row[0].startswith('First'):
                        continue
                    full  = _clean(row[0]) if row else ''
                    email = _clean(row[1]) if len(row) > 1 else ''
                    phone = row[2] if len(row) > 2 else ''
                    combo = _clean(row[3]) if len(row) > 3 else ''
                    parts = full.split()
                    if not parts:
                        continue
                    fn = parts[0]; ln = ' '.join(parts[1:]) if len(parts) > 1 else ''
                    parent = add_parent(email, phone, source='ff_camp_jun_2024')
                    if parent:
                        add_player(parent, fn, ln, combo, '', '', '', '', 'ff_camp_jun_2024')

        # ── 6. FF Camp June 2024 (Responses) ─────────────────────────────
        f = DOCS_DIR / 'Future Footballers Camp June 22-23 2024 (Risposte) - Risposte del modulo 1.csv'
        if f.exists():
            with open(f, encoding='utf-8-sig', errors='replace') as fh:
                for row in csv.DictReader(fh):
                    fn_raw = _clean(row.get('First Name', ''))
                    ln_raw = _clean(row.get('Last Name', ''))
                    if not fn_raw:
                        continue
                    parts  = fn_raw.split()
                    fn = parts[0]
                    ln = _strip_suffix(ln_raw or (' '.join(parts[1:]) if len(parts) > 1 else ''))
                    combo  = _clean(row.get('DOB', ''))
                    parent = add_parent(row.get('Email', ''), row.get('Phone Number', ''), source='ff_camp_jun_2024')
                    if parent:
                        add_player(parent, fn, ln, combo, '', '', '', '', 'ff_camp_jun_2024')

        # ── 7. Future Footballers Program (2 players per row) ────────────
        f = DOCS_DIR / 'Future Footballers Program - Risposte del modulo 1.csv'
        if f.exists():
            with open(f, encoding='utf-8-sig', errors='replace') as fh:
                reader = csv.reader(fh)
                next(reader, None)  # skip header
                for row in reader:
                    if not row or not any(row):
                        continue
                    for offset in (1, 12):
                        fn    = _clean(row[offset])     if len(row) > offset     else ''
                        ln    = _clean(row[offset + 1]) if len(row) > offset + 1 else ''
                        sex   = row[offset + 2]         if len(row) > offset + 2 else ''
                        dob_r = row[offset + 3]         if len(row) > offset + 3 else ''
                        phone = row[offset + 4]         if len(row) > offset + 4 else ''
                        email = _clean(row[offset + 5]) if len(row) > offset + 5 else ''
                        team  = _clean(row[offset + 6]) if len(row) > offset + 6 else ''
                        pos   = _clean(row[offset + 7]) if len(row) > offset + 7 else ''
                        shirt = _clean(row[offset + 8]) if len(row) > offset + 8 else ''
                        if fn and ln:
                            parent = add_parent(email, phone, source='ff_program')
                            if parent:
                                add_player(parent, fn, ln, dob_r, sex, team, pos, shirt, 'ff_program')

        # ── 8. NKC Spring Break 2025 ─────────────────────────────────────
        f = DOCS_DIR / 'NKC Spring Break Clinic (Risposte) - Risposte del modulo 1.csv'
        if f.exists():
            with open(f, encoding='utf-8-sig', errors='replace') as fh:
                for row in csv.DictReader(fh):
                    fn = _clean(row.get('First Name', ''))
                    ln = _clean(row.get('Last Name', ''))
                    if not fn or fn == 'Informazioni':
                        continue
                    email = _clean(row.get('E-mail', '')) or _clean(row.get('Mobile phone', ''))
                    phone = _phone(_clean(row.get('Mobile phone', '')) or _clean(row.get('E-mail', '')))
                    parent = add_parent(email, phone, source='nkc_spring_2025')
                    if parent:
                        add_player(parent, fn, ln, row.get('DOB', ''),
                                   row.get('Sex', ''), row.get('Current team', ''),
                                   '', '', 'nkc_spring_2025')

        # ── 9. Winter Clinic Dec 2024 ─────────────────────────────────────
        f = DOCS_DIR / 'Winter Clinic December 27 (Responses) - Form Responses 1.csv'
        if f.exists():
            with open(f, encoding='utf-8-sig', errors='replace') as fh:
                for row in csv.DictReader(fh):
                    full = _clean(row.get("Player's full name", ''))
                    if not full:
                        continue
                    parts = full.split()
                    fn = parts[0]; ln = ' '.join(parts[1:]) if len(parts) > 1 else ''
                    parent_name = _clean(row.get('Parent full name', ''))
                    pfn = parent_name.split()[0] if parent_name else ''
                    pln = ' '.join(parent_name.split()[1:]) if parent_name and len(parent_name.split()) > 1 else ''
                    email = _clean(row.get('Best email to send information to', '')) or \
                            _clean(row.get('Email Address', ''))
                    parent = add_parent(email, '', pfn, pln, source='winter_2024')
                    if parent:
                        add_player(parent, fn, ln,
                                   row.get("Player's date of birth", ''),
                                   row.get('Gender', ''),
                                   row.get('Current club (if applicable)', ''),
                                   row.get('Preferred Positions', ''),
                                   '', 'winter_2024',
                                   notes=_clean(row.get('Any additional comments that you would like to share', '')))

        # ── Try to link to existing Client accounts by email ─────────────
        if not dry:
            from django.contrib.auth.models import User
            linked = 0
            for cp in ContactParent.objects.filter(client__isnull=True).exclude(email=''):
                user = User.objects.filter(email__iexact=cp.email).first()
                if user and hasattr(user, 'client'):
                    cp.client    = user.client
                    cp.linked_at = timezone.now()
                    cp.save(update_fields=['client', 'linked_at'])
                    linked += 1
            if linked:
                self.stdout.write(verb(f'Auto-linked {linked} contacts to existing accounts'))

        self.stdout.write(verb(
            f'\n{"DRY RUN — " if dry else ""}Import complete:\n'
            f'  Parents : {parents_new} new, {parents_skip} skipped (existing)\n'
            f'  Players : {players_new} new, {players_skip} skipped (existing)\n'
        ))
