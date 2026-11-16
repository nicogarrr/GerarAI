# Ownership view and manager rails

Only ownership page is changed. Both view nav and manager chip rail use the
existing scroll-affordance-x pattern. Direct component DOM test asserts both.
EarningsDayStrip removed from this lot after parent requested preserving the
intentional hidden-scrollbar contract; its component and shared guard test
are identical to base. The earlier screenshot includes EarningsDayStrip from
superseded SHA9a297c03 and must not be treated as final evidence.

Focused config measures ownership page in full and excludes ownership-en
because of local auth import setup; CI full suite remains required.
