"""Swig transfer review and signing in the Safe Signer cartridge."""
from binascii import hexlify, unhexlify
from hashlib import sha256
from safe_keccak import keccak256
import lcd
import optiga
import save
import ui
import time
import wedgie

_SWIG = "swigypWHEksbC64pWKwah1WTeh9JXwx8H1rJHLdbQMB"
_NETWORKS = ("local", "devnet")
_SAVE = "solana_profile"
_DEVNET_SAVE = "solana_devnet_profile"
_APPROVAL_MS = 60000
_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_SYSTEM = "11111111111111111111111111111111"
_TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
_INSTRUCTIONS = "Sysvar1nstructions1111111111111111111111111"
_MAX_AMOUNT = 10_000_000


def address_bytes(address):
    if type(address) is not str or not 32 <= len(address) <= 44:
        raise ValueError("invalid address length")
    value = 0
    for char in address:
        value = value * 58 + _ALPHABET.index(char)
    zeros = len(address) - len(address.lstrip("1"))
    try:
        raw = value.to_bytes(32, "big")
    except OverflowError:
        raise ValueError("invalid address encoding")
    if len(raw) - len(raw.lstrip(b"\x00")) != zeros:
        raise ValueError("invalid address encoding")
    return raw


def _int_le(value, size, minimum=0):
    if type(value) is not int or not minimum <= value < (1 << (size * 8)):
        raise ValueError("integer out of bounds")
    return value.to_bytes(size, "little")


def _meta(address, writable):
    return address_bytes(address) + bytes((writable, 0)) + bytes(6)


def transfer_hash(swig, wallet, recipient, amount, slot, counter):
    """Rebuild the SDK's compact SignV2 payload for exactly one System transfer."""
    accounts = (swig, wallet, _SYSTEM, _INSTRUCTIONS, recipient)
    if len(set(accounts)) != 5 or type(amount) is not int or not 0 < amount <= _MAX_AMOUNT:
        raise ValueError("unsupported local SOL transfer")
    # One instruction. Program index 4, account indices 1 and 5, 12 bytes of data.
    compact = b"\x01\x04\x02\x01\x05\x0c\x00\x02\x00\x00\x00" + _int_le(amount, 8, 1)
    metas = (
        _meta(swig, 1) + _meta(wallet, 1) + _meta(_SYSTEM, 0)
        + _meta(_INSTRUCTIONS, 0) + _meta(_SYSTEM, 0) + _meta(recipient, 1)
    )
    return keccak256(compact + metas + _int_le(slot, 8) + _int_le(counter, 4, 1))


def token_hash(swig, wallet, source, mint, recipient, amount, slot, counter):
    """Rebuild exactly one six-decimal legacy SPL TransferChecked."""
    accounts = (swig, wallet, _SYSTEM, _INSTRUCTIONS, _TOKEN, source, mint, recipient)
    if len(set(accounts)) != 8 or type(amount) is not int or not 0 < amount <= _MAX_AMOUNT:
        raise ValueError("unsupported local token transfer")
    compact = b"\x01\x04\x04\x05\x06\x07\x01\x0a\x00\x0c" + _int_le(amount, 8, 1) + b"\x06"
    metas = b"".join(_meta(address, writable) for address, writable in zip(accounts, (1, 1, 0, 0, 0, 1, 0, 1)))
    return keccak256(compact + metas + _int_le(slot, 8) + _int_le(counter, 4, 1))


def _pda(label, seed, bump):
    return sha256(label + seed + _int_le(bump, 1) + address_bytes(_SWIG) + b"ProgramDerivedAddress").digest()


def _profile(request):
    network = request.get("network")
    if network not in _NETWORKS:
        raise ValueError("unknown Solana network")
    swig, wallet, mint = request["swig"], request["wallet"], request.get("mint")
    config_id = request["config_id"]
    if type(config_id) is not str or len(config_id) != 64:
        raise ValueError("invalid Swig ID")
    if address_bytes(swig) != _pda(b"swig", unhexlify(config_id), request["config_bump"]):
        raise ValueError("invalid Swig config PDA")
    if address_bytes(wallet) != _pda(b"swig-wallet-address", address_bytes(swig), request["wallet_bump"]):
        raise ValueError("invalid Swig wallet PDA")
    if mint is not None:
        address_bytes(mint)
    return {"network": network, "swig": swig, "wallet": wallet, "mint": mint}


def _draw_time(display, seconds):
    display.fill_rect(24, 169, 192, 12, ui.WHITE)
    display.fill_rect(24, 173, 152, 4, ui.GREY)
    width = 152 * seconds // (_APPROVAL_MS // 1000)
    if width:
        display.fill_rect(24, 173, width, 4, ui.GREEN_D)
    display.text("%ds" % seconds, 184, 170, ui.INK)


class _ApprovalKeys:
    """Add a display tick to the stock UI's physical key polling."""
    def __init__(self, display, keys, drawn):
        self.display, self.keys, self.drawn = display, keys, drawn
        self.seconds = _APPROVAL_MS // 1000

    def pressed(self):
        pressed = self.keys.pressed()
        remaining = _APPROVAL_MS - time.ticks_diff(time.ticks_ms(), self.drawn)
        seconds = (max(0, remaining) + 999) // 1000
        if seconds != self.seconds:
            self.seconds = seconds
            _draw_time(self.display, seconds)
            self.display.show_rect(24, 169, 192, 12)
        if time.ticks_diff(time.ticks_ms(), self.drawn) >= _APPROVAL_MS:
            return ()
        return pressed


def _review(display, title, amount, addresses, yes, prompt=None):
    keys = lcd.Keys(physical=True)
    keys.pressed()
    display.fill(ui.WHITE)
    ui.band(display)
    display.center_text(title, 36, ui.INK, 2)
    display.center_text(amount, 59, ui.INK, 2)
    for (label, address), y in zip(addresses, (86, 132)):
        display.center_text(label, y, ui.MUTED, 1)
        display.center_text(address[:22], y + 15, ui.INK, 1)
        display.center_text(address[22:], y + 28, ui.INK, 1)
    ui.buttons(display, yes, "reject")
    _draw_time(display, _APPROVAL_MS // 1000)
    display.show()
    ui.drawn = time.ticks_ms()
    if prompt:
        prompt()
    remaining = max(0, _APPROVAL_MS - time.ticks_diff(time.ticks_ms(), ui.drawn))
    return ui.wait(_ApprovalKeys(display, keys, ui.drawn), remaining)


def _key_slot(network):
    return optiga.KEY3 if network == "devnet" else optiga.KEY4


def _save_name(network):
    return _DEVNET_SAVE if network == "devnet" else _SAVE


def _enroll(display, request, saved, prompt=None):
    profile = _profile(request)
    if saved is not None:
        if any(saved.get(k) != v for k, v in profile.items()):
            raise ValueError("Solana key is already bound")
        return saved
    key_slot = _key_slot(profile["network"])
    existing = request.get("existing_key")
    if existing is not None and profile["network"] != "local":
        raise ValueError("use a fresh key for a public network")
    if not _review(display, "Bind Solana key", profile["network"].upper(),
                   (("WALLET", profile["wallet"]), ("SPL MINT", profile["mint"] or "Disabled")), "bind key", prompt):
        return None
    chip = optiga.Chip()
    try:
        if existing is not None:
            if type(existing) is not str or len(existing) != 130:
                raise ValueError("invalid existing key")
            public = unhexlify(existing)
            if public[0] != 4:
                raise ValueError("invalid existing key")
            proof = sha256(b"wedgie-solana-local-key-proof-v1").digest()
            r, s = chip.sign(key_slot, proof)
            if not chip.verify(proof, r, s, pub=public):
                raise ValueError("KEY4 does not match this public key")
        else:
            if chip.metadata(key_slot).get(0xe0) not in (None, b"\x00"):
                raise ValueError("Solana key slot is occupied")
            public = chip.genkey(key_slot)
        if len(public) != 65 or public[0] != 4:
            raise ValueError("invalid chip public key")
        profile["key"] = hexlify(bytes((2 | (public[-1] & 1),)) + public[1:33]).decode()
        save.store(_save_name(profile["network"]), profile)
        return profile
    finally:
        chip.close()


def _sign(display, request, profile, prompt=None):
    if profile is None:
        raise ValueError("bind a Solana wallet first")
    if any(request.get(k) != profile[k] for k in ("network", "swig", "wallet")):
        raise ValueError("request does not match the enrolled Solana wallet")
    swig, wallet = profile["swig"], profile["wallet"]
    recipient, amount = request["recipient"], request["amount"]
    slot, counter = request["slot"], request["counter"]
    cluster = profile["network"].upper()
    kind = request.get("kind")
    if kind == "sol":
        message = transfer_hash(swig, wallet, recipient, amount, slot, counter)
        title = cluster + " SOL"
        shown = "%d.%09d" % divmod(amount, 1_000_000_000)
        addresses = (("FROM", wallet), ("TO", recipient))
    elif kind == "token":
        mint = profile["mint"]
        if not mint or request.get("mint") != mint:
            raise ValueError("token mint is not enrolled")
        message = token_hash(swig, wallet, request["source"], mint, recipient, amount, slot, counter)
        title = cluster + " SPL"
        shown = "%d.%06d" % divmod(amount, 1_000_000)
        addresses = (("MINT", mint), ("TO TOKEN ACCOUNT", recipient))
    else:
        raise ValueError("unsupported Solana instruction")
    encoded = hexlify(message).decode()
    if request.get("expected") != encoded:
        raise ValueError("transfer differs from host message")
    if not _review(display, title, shown, addresses, "sign", prompt):
        return None
    chip = optiga.Chip()
    try:
        r, s = chip.sign(_key_slot(profile["network"]), sha256(message).digest())
    finally:
        chip.close()
    if not (0 < r < _ORDER and 0 < s < _ORDER):
        raise ValueError("invalid chip signature")
    signature = r.to_bytes(32, "big") + min(s, _ORDER - s).to_bytes(32, "big")
    return {"message": encoded, "signature": hexlify(signature).decode()}


def handle(display, request, review=None):
    kind = request["type"]
    network = request.get("network", "local")
    if network not in _NETWORKS:
        raise ValueError("unknown Solana network")
    profile = save.load(_save_name(network))
    if profile is not None and (type(profile) is not dict or profile.get("network") != network):
        raise ValueError("saved Solana profile belongs to another network")
    mid = request.get("id")

    events = request.get("prompt_events") == 1

    def prompt():
        if events:
            wedgie.send({"id": mid, "type": "sol_prompt", "timeout_ms": _APPROVAL_MS})
        if review:
            review(ui.drawn, _APPROVAL_MS)

    notify = prompt if events or review else None
    if kind == "sol_status":
        result = {"profile": profile}
    elif kind == "sol_enroll":
        profile = _enroll(display, request, profile, notify)
        result = {"profile": profile} if profile else None
    elif kind == "sol_sign":
        result = _sign(display, request, profile, notify)
    else:
        raise ValueError("unknown Solana request")
    if result is None:
        reason = "declined" if ui.said_no else "expired"
        wedgie.send({"id": mid, "type": "refused", "reason": reason})
        ui.page(display, "Declined" if ui.said_no else "Approval expired")
        time.sleep_ms(900)
    else:
        response = {"id": mid, "type": "sol_ok"}
        response.update(result)
        wedgie.send(response)
