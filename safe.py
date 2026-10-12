# Safe Signer: the wedgie signs Safe{Wallet} transactions with a key that lives in its secure chip, an
# ATECC608 or an OPTIGA Trust M (whichever it has).
#
# The key: made once, on the wedgie (A on its screen), in the Trust M's key slot 2 or the ATECC608's slot 0.
# It never leaves the chip. An ATECC608 as shipped can't hold a key until its config is written and locked:
# the question says so, and the yes locks it (for good; the old Wallet's table, atecc.CONFIG).
# Its public key is saved (/saves/safe/key, with which chip) because the Trust M hands it out only when it
# makes the key.
# On chain the key is a passkey-style Safe owner: Safe's SafeWebAuthnSignerFactory makes a small signer
# contract from (x, y), and that contract's address is added as an owner of the Safe.
#
# A host sends the transaction's fields, not a hash. The wedgie works out the Safe tx hash itself
# (EIP-712, safe_keccak), shows what the transaction does, and signs only on a real A press. What it
# signs is the WebAuthn message the signer contract checks: sha256(authenticatorData + sha256(clientDataJSON)),
# with the Safe tx hash as the challenge. The wedgie picks authenticatorData and clientDataJSON itself.
#
# USB (one JSON line each way; everything else goes to the slot, so hello/shot/jobs still work):
#   {"id":1,"type":"safe_sign","tx":{"chainId":8453,"safe":"0x..","to":"0x..","value":"0","data":"0x",
#    "operation":0,"safeTxGas":0,"baseGas":0,"gasPrice":0,"gasToken":"0x0..","refundReceiver":"0x0..","nonce":0}}
#   -> {"id":1,"type":"safe_sig","safeTxHash":"0x..","x":"0x..","y":"0x..","r":"0x..","s":"0x..",
#       "authenticatorData":"0x..","clientDataFields":"\"origin\":\"https://wedgie.dev\""}
#   -> {"id":1,"type":"refused"} (Y, or no answer in 2 minutes) or {"type":"error","error":".."}
#   hello answers also carry "safe": {"x","y","chip"} (or null: no key yet) and "signer": its Safe owner address
#   (safe_addr.py; the home screen shows it, wedgie.dev/safe checks it against its own).
#   {"type":"safe_list"} -> {"type":"safe_list","safes":["8453:0x..", ...]}: the Safes this wedgie knows it's
#   in, newest first, so any computer can list them. {"type":"safe_note","chainId":8453,"safe":"0x.."} adds
#   one (a host that made or opened it); signing for a Safe adds it too. Just a list of addresses: a host
#   checks on chain that the wedgie really is an owner before it shows one.
import sys, select, json, time, gc, binascii, hashlib
import lcd as L
import wedgie as W
import save
import ui
from ui import WHITE, INK, MUTED, GREEN_D, RED

FW = "safe-12"
RP_ID = b"wedgie.dev"
FIELDS = '"origin":"https://wedgie.dev"'
ASK_MS = 120000

DOMAIN_TYPEHASH = binascii.unhexlify("47e79534a245952e8b16893a336b85a3d9ea9fa8c573f3d803afb92a79469218")
SAFE_TX_TYPEHASH = binascii.unhexlify("bb8310d486368db6bd6f849402fdd73ad53d316b5a4b2644ad6efe0f941286d8")

CHAINS = {1: "Ethereum", 10: "Optimism", 100: "Gnosis", 137: "Polygon", 8453: "Base", 42161: "Arbitrum",
          84532: "Base Sepolia", 11155111: "Sepolia"}
SAFES_MAX = 32          # Safes the wedgie remembers (save "safes")
CHUNK = 4000            # hex chars per safe_data line (a USB line is at most 6 KB)
# bytes of tx data the wedgie takes in pieces. Joining them needs one free block that size, and how big a
# block a used RP2040 heap still has varies: on a virtual RP2040 (wedgie-dev tools/safechip.mjs) 12 KB
# passed one run and failed another, 16 KB once, 20 KB never. 8 KB passes every run, with room.
MAX_DATA = 8000

d = None
keys = None
_poll = None
key = None          # {"x": "0x..", "y": "0x..", "chip": "ATECC608" | "OPTIGA Trust M"} or None (no chip: a Trust M)
signer = None       # its Safe owner address, "0x.." checksummed (safe_addr.py), or None
note = ""           # one line under the home screen (the last thing that happened)
dirty = True


# ---- small helpers ----------------------------------------------------------------------------

def unhex(s):
    s = str(s or "")
    if s[:2] in ("0x", "0X"):
        s = s[2:]
    if len(s) % 2:
        raise ValueError("odd hex")
    return binascii.unhexlify(s)


def num(v):
    if isinstance(v, int):
        n = v
    else:
        v = str(v or "0")
        n = int(v[2:], 16) if v[:2] in ("0x", "0X") else int(v)
    if n < 0 or n >> 256:
        raise ValueError("bad number")
    return n


def addr(v):
    b = unhex(v)
    if len(b) != 20:
        raise ValueError("bad address")
    return "0x" + binascii.hexlify(b).decode()


def word(n):
    return n.to_bytes(32, "big")


def aword(a):
    return bytes(12) + unhex(a)


def short(a):
    return a[:6] + ".." + a[-4:]


def amount(n, dec):
    if not dec:
        return str(n)
    w, f = n // 10 ** dec, n % 10 ** dec
    f = ("%0" + str(dec) + "d") % f
    f = f.rstrip("0")[:6]
    return "%d.%s" % (w, f) if f else str(w)


def hx(b):
    return "0x" + binascii.hexlify(b).decode()


# ---- the transaction --------------------------------------------------------------------------

# Kept as bytes, each piece decoded as it comes: hex strings joined and then decoded needed ~5x the data at
# once and ran a virtual RP2040 out of memory at 12 KB (wedgie-dev tools/safechip.mjs). As bytes the join
# needs 2x, once.
pieces = []             # a big tx's data, sent ahead in safe_data lines (bytes, one per piece)
have = 0                # bytes of it so far
# The join needs one free block of up to MAX_DATA, and any code change moves what's left of a used heap (a
# change to the screens alone made 8 KB fail every run). So the first piece takes that block, before the
# pieces scatter the heap, and parse frees it just before the join, which then lands in it.
room = None


def hold():
    global room
    if room is None:
        gc.collect()
        try:
            room = bytearray(MAX_DATA + 64)
        except MemoryError:
            pass


def on_data(mid, m):
    """{"type":"safe_data","at":<bytes so far>,"hex":"..."}: a piece of the next tx's data. at 0 starts over."""
    global pieces, have
    at, h = m.get("at"), str(m.get("hex") or "")
    if at == 0:
        pieces, have = [], 0
        hold()
    if have + len(h) // 2 > MAX_DATA:
        pieces, have = [], 0
        W.send({"id": mid, "type": "error", "error": "too big: a wedgie takes up to %d bytes of tx data" % MAX_DATA})
        return
    if at != have or len(h) % 2 or len(h) > CHUNK:
        pieces, have = [], 0
        W.send({"id": mid, "type": "error", "error": "bad piece"})
        return
    try:
        b = binascii.unhexlify(h)
    except Exception:
        pieces, have = [], 0
        W.send({"id": mid, "type": "error", "error": "bad piece"})
        return
    h = m = None
    pieces.append(b)
    have += len(b)
    W.send({"id": mid, "type": "safe_data", "have": have})


def parse(t):
    """The fields, checked and normalized. Raises ValueError on anything off. data "@" = the pieces sent ahead."""
    global pieces, have, room
    room = None
    data = t.get("data") or "0x"
    if data == "@":
        gc.collect()
        data = b"".join(pieces)
        pieces, have = [], 0
        gc.collect()
    else:
        data = unhex(data)
    tx = {"chainId": num(t["chainId"]), "safe": addr(t["safe"]), "to": addr(t["to"]),
          "value": num(t.get("value", 0)), "data": data,
          "operation": num(t.get("operation", 0)), "safeTxGas": num(t.get("safeTxGas", 0)),
          "baseGas": num(t.get("baseGas", 0)), "gasPrice": num(t.get("gasPrice", 0)),
          "gasToken": addr(t.get("gasToken") or "0x" + "0" * 40),
          "refundReceiver": addr(t.get("refundReceiver") or "0x" + "0" * 40), "nonce": num(t["nonce"])}
    if tx["operation"] > 1:
        raise ValueError("bad operation")
    return tx


def safe_tx_hash(tx):
    """EIP-712, as Safe 1.3+ computes getTransactionHash."""
    from safe_keccak import keccak256 as k
    domain = k(DOMAIN_TYPEHASH + word(tx["chainId"]) + aword(tx["safe"]))
    st = k(b"".join((SAFE_TX_TYPEHASH, aword(tx["to"]), word(tx["value"]), k(tx["data"]),
                     word(tx["operation"]), word(tx["safeTxGas"]), word(tx["baseGas"]), word(tx["gasPrice"]),
                     aword(tx["gasToken"]), aword(tx["refundReceiver"]), word(tx["nonce"]))))
    return k(b"\x19\x01" + domain + st)


BIG = "big"         # a line kind: big text (the amount, the limit)
ADDR = "addr"       # a line kind: an address in full, with its blockie (safe_blockie) beside it
GAP = ("", INK, "gap")  # a line: 6 px of space


def _h(line, big=False):
    """Pixels a line takes on a page (big: addresses with the big blockie)."""
    k = line[2] if len(line) > 2 else None
    return (30 if len(line[0]) <= 10 else 22) if k == BIG else (52 if big else 38) if k == ADDR else 6 if k == "gap" else 12


def _draw(lines, y, bottom=182, big=False):
    """Lines of (text, color) or (text, color, kind) from y; stops before bottom. Returns the y under them.
    big: each address gets a 48 px blockie and 3 lines of 14 (the caller checks they fit)."""
    import safe_blockie
    for l in lines:
        if y + _h(l, big) > bottom:
            break
        s, c, k = l[0], l[1], (l[2] if len(l) > 2 else None)
        if k == BIG and len(s) <= 10:
            d.center_text(s, y + 3, c, 3)
        elif k == BIG and len(s) <= ui.COLS_BIG:
            d.center_text(s, y + 2, c, 2)
        elif k == ADDR and big:
            safe_blockie.draw(d, s, 30, y + 2, 6, MUTED)
            for i in range(3):
                d.text(s[i * 14:i * 14 + 14], 94, y + 4 + i * 15, c)
        elif k == ADDR:
            safe_blockie.draw(d, s, 12, y + 2, 4, MUTED)
            d.text(s[:22], 54, y + 6, c)
            d.text(s[22:], 54, y + 20, c)
        elif s:
            d.center_text(s, y + (4 if k == BIG else 0), c)
        y += _h(l)
    return y


def webauthn_digest(h):
    """What the chip signs: the WebAuthn message the signer contract rebuilds (WebAuthn.sol)."""
    auth = hashlib.sha256(RP_ID).digest() + b"\x05\x00\x00\x00\x00"     # user present + verified
    ch = binascii.b2a_base64(h).decode().strip().rstrip("=").replace("+", "-").replace("/", "_")
    cdj = '{"type":"webauthn.get","challenge":"' + ch + '",' + FIELDS + "}"
    return auth, hashlib.sha256(auth + hashlib.sha256(cdj.encode()).digest()).digest()


# ---- the chip ---------------------------------------------------------------------------------

N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551     # P-256's order


def _atecc():
    """The ATECC608 if one answers on GP4/GP5, else None (then it's a Trust M)."""
    try:
        import atecc
        a = atecc.ATECC608(sda=4, scl=5)
        a.wake()
        a.sleep()
        return a
    except MemoryError:                 # out of memory isn't "no ATECC608"
        raise
    except Exception:
        return None


def _unload():
    for m in ("optiga", "trustm", "atecc"):
        if m in sys.modules:
            del sys.modules[m]
    gc.collect()


def key_question():
    """What the yes to "Make a key?" does on this wedgie's chip."""
    try:
        a = _atecc()
        if not a:
            return ["Replaces chip key slot 2."]
        if not a.lock_state()["configLocked"]:
            return ["Locks the chip for good.", "Can't undo."]
        return ["Replaces chip key slot 0."]
    except Exception:                   # make_key says what went wrong
        return ["Replaces the chip's key."]
    finally:
        _unload()


def make_key():
    global key
    ui.progress("Making your key", "in the chip", False)
    try:
        a = _atecc()
        if a:
            if not a.lock_state()["configLocked"]:
                a.write_config()                # checked byte for byte, then locked: permanent
                a.lock_config()
            x, y = a.genkey_new(0)
            key = {"x": "0x%064x" % x, "y": "0x%064x" % y, "chip": "ATECC608"}
        else:
            import optiga
            pub = optiga.Chip().genkey(optiga.KEY2)     # 65 bytes: 04 X Y
            key = {"x": hx(pub[1:33]), "y": hx(pub[33:65]), "chip": "OPTIGA Trust M"}
        save.store("key", key)
        save.delete("signer")                   # a new key, a new address
        save.delete("safes")                    # and none of the old key's Safes
    finally:
        _unload()
    find_signer()


def find_signer():
    """Its Safe owner address, worked out once per key (two keccaks in plain Python) and saved."""
    global signer
    if not key:
        signer = None
        return
    s = save.load("signer", None)
    if s and s.get("x") == key["x"]:
        signer = s["address"]
        return
    ui.progress("Finding your address", "Safe owner", False)
    import safe_addr
    try:
        signer = safe_addr.address(unhex(key["x"]), unhex(key["y"]))
    finally:
        del sys.modules["safe_addr"]
        gc.collect()
    save.store("signer", {"x": key["x"], "address": signer})


def sign(digest):
    """(r, s) by the key's chip, s low (N - s is the same signature)."""
    try:
        if key.get("chip") == "ATECC608":
            a = _atecc()
            if not a:
                raise OSError("the key is in an ATECC608 and none answered")
            r, s = a.sign(digest, 0)
        else:
            import optiga
            r, s = optiga.Chip().sign(optiga.KEY2, digest)
    finally:
        _unload()
    return r, (N - s if s > N // 2 else s)


# ---- screens ----------------------------------------------------------------------------------

def draw_home():
    """The title, its Safe owner address (the same on every chain) as a big blockie and big text."""
    d.fill(WHITE)
    ui.band(d)
    ui.title(d, "Safe Signer", 42, 1)
    if key and signer:
        import safe_blockie
        safe_blockie.draw(d, signer, 84, 70, 9, MUTED)
        for i in range(3):
            d.center_text(signer[i * 14:i * 14 + 14], 154 + i * 22, INK, 2)
    elif key:
        _draw([(key["x"][:22], INK), (key["x"][22:44], INK), (key["x"][44:], INK)], 80, 220)
    else:
        _draw([("No key", INK, BIG)], 90, 180)
    if note:
        d.center_text(note[:ui.COLS_SMALL], 226 if key else 170, MUTED)
    if not key:
        ui.buttons(d, "make a key", "not now")
    d.show()


def _screen(head, lines, yes, k, foot="", safe=None):
    """One page of the question: the action big, its lines, which Safe small at the bottom. True on a
    real A, False on Y or no answer."""
    d.fill(WHITE)
    ui.band(d)
    ui.title(d, head, 42, 1)
    y = _draw(lines, 68, 166, sum(_h(l, True) for l in lines) <= 98)    # the big blockie wherever it fits
    if safe:                            # which Safe: its blockie (bigger when there's room), chain, address
        import safe_blockie
        c = 3 if y <= 156 else 2
        safe_blockie.draw(d, safe, 8, 182 - 8 * c, c, MUTED)
        d.text(foot[:25], 16 + 8 * c, 170, MUTED)
    elif foot:
        d.center_text(foot[:ui.COLS_SMALL], 170, MUTED)
    ui.buttons(d, yes, "no")
    d.show()
    k.pressed()                         # a press made before this page was up doesn't answer it
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < ASK_MS:
        for kk in k.pressed():
            if kk in ("A", "Y"):
                return kk == "A"
        time.sleep_ms(20)
    return False


def confirm(tx):
    """The transaction on the screen, a page per action in a batch. True only on A through every page."""
    k = L.Keys(physical=True)
    k.pressed()
    sf = tx["safe"]
    foot = "%s %s" % (CHAINS.get(tx["chainId"], "chain %d" % tx["chainId"]), short(tx["safe"]))
    tail = [("pays a gas refund", RED)] if tx["gasPrice"] else []
    import safe_read
    try:
        acts = safe_read.batch(tx)
        pages = [safe_read.describe(tx)] if acts is None else safe_read.fold(acts)
    finally:
        del acts
        del sys.modules["safe_read"]
        gc.collect()
    n = len(pages)
    for i, (head, lines) in enumerate(pages):
        last = i == n - 1
        if not _screen(head, lines + (tail if last else []), "sign" if last else "next", k,
                       "%d/%d %s" % (i + 1, n, foot) if n > 1 else foot, sf):
            return False
    return True


# ---- requests ---------------------------------------------------------------------------------

def on_sign(mid, t):
    global note
    if not key:
        W.send({"id": mid, "type": "error", "error": "no key yet: press A on the wedgie to make one"})
        return
    try:
        tx = parse(t or {})
    except Exception as e:
        W.send({"id": mid, "type": "error", "error": "bad tx: %s" % e})
        return
    ui.progress("Reading the transaction", "Safe tx hash", False)
    h = safe_tx_hash(tx)
    gc.collect()
    if not confirm(tx):
        note = "said no"
        W.send({"id": mid, "type": "refused", "safeTxHash": hx(h)})
        return
    ui.progress("Signing", "in the chip", False)
    auth, dg = webauthn_digest(h)
    r, s = sign(dg)
    note = "signed"
    try:
        keep_safe(tx["chainId"], tx["safe"])
    except Exception as e:              # the list is a convenience: never lose a signature over it
        sys.print_exception(e)
    W.send({"id": mid, "type": "safe_sig", "safeTxHash": hx(h), "x": key["x"], "y": key["y"],
            "r": "0x%064x" % r, "s": "0x%064x" % s, "authenticatorData": hx(auth), "clientDataFields": FIELDS})


def keep_safe(chain, safe):
    """Remember a Safe (newest first, at most SAFES_MAX). Writes the flash only for a new one."""
    k = "%d:%s" % (chain, safe.lower())
    l = save.load("safes", [])
    if l[:1] == [k]:
        return len(l)
    if k in l:
        l.remove(k)
    l.insert(0, k)
    del l[SAFES_MAX:]
    save.store("safes", l)
    return len(l)


def handle(m):
    global dirty
    mid, t = m.get("id"), m.get("type")
    if t == "safe_sign":
        on_sign(mid, m.get("tx"))
        dirty = True
    elif t == "safe_data":
        on_data(mid, m)
    elif t == "safe_list":
        W.send({"id": mid, "type": "safe_list", "safes": save.load("safes", [])})
    elif t == "safe_note":
        try:
            n = keep_safe(num(m.get("chainId")), addr(m.get("safe")))
        except ValueError as e:
            W.send({"id": mid, "type": "error", "error": "bad safe: %s" % e})
            return
        W.send({"id": mid, "type": "ok", "safes": n})
    elif t == "hello":
        W.send(W.hello(mid, running="safe", app=FW, safe=key, signer=signer, safe_chunk=CHUNK))
    else:                               # hello's cousins, shots, jobs, open: the slot's
        import slot
        slot.handle(m)
        dirty = True


def pump():
    """One request per call, read through the one line reader (wedgie.lines)."""
    global dirty
    R = W.lines()
    line = R.pump(_poll)
    if R.intr:                          # a Ctrl-C while sealed: the red question (hatch.py)
        R.intr = False
        if W.SEALED and not W.is_open():
            try:
                import hatch
                ok = hatch.ctrl_c()
            except Exception as e:
                sys.print_exception(e)
                ok = False
            if ok:
                raise KeyboardInterrupt
            dirty = True
    if line is False:
        W.send({"type": "error", "error": "line too long"})
    elif line and line.strip():
        try:
            m = json.loads(line)
        except Exception:
            line = None
            gc.collect()
            W.send({"type": "error", "error": "bad json"})
            return
        line = None
        if not isinstance(m, dict):
            return
        try:
            handle(m)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            dirty = True
            W.failed(m.get("id"), e)


def run():
    global d, keys, _poll, key, dirty, note
    d = L.LCD()
    keys = L.Keys(physical=True)
    _poll = select.poll()
    _poll.register(sys.stdin, select.POLLIN)
    key = save.load("key", None)
    try:
        find_signer()
    except Exception as e:              # the address is for the screen; signing works without it
        sys.print_exception(e)
    W.send(W.hello(None, type="ready", running="safe", app=FW, safe=key, signer=signer, safe_chunk=CHUNK))
    while True:
        for k in keys.pressed():
            if k == "A" and not key:
                if ui.ask(d, "Make a key?", key_question()):
                    try:
                        make_key()
                        note = "key made"
                    except Exception as e:
                        sys.print_exception(e)
                        note = "no key: %s" % e
                dirty = True
        pump()
        if dirty:
            draw_home()
            dirty = False
        time.sleep_ms(20)
