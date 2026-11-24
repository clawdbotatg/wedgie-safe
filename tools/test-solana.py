"""Run the cartridge's Solana checks with a recording chip and no device."""
import hashlib
from pathlib import Path
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
hardware = {name: ModuleType(name) for name in ("lcd", "optiga", "save", "ui", "wedgie")}
for color in ("WHITE", "INK", "MUTED", "GREY", "GREEN_D", "RED"):
    setattr(hardware["ui"], color, 0)
with patch.dict(sys.modules, hardware):
    import safe
    import safe_sol


def address(number):
    raw = bytes([number]) * 32
    value = int.from_bytes(raw, "big")
    digits = ""
    while value:
        value, digit = divmod(value, 58)
        digits = safe_sol._ALPHABET[digit] + digits
    return "1" * 32 if not number else digits


class SolanaDispatch(unittest.TestCase):
    def setUp(self):
        self.wire = Mock(SEALED=True)
        self.wire.is_open.return_value = False
        self.wire.hello.side_effect = lambda mid, **fields: dict(fields, id=mid)
        self.display = SimpleNamespace(width=240, height=240)
        self.key = {"chip": "OPTIGA Trust M"}
        self.lend, self.unload = Mock(), Mock()
        patcher = patch.multiple(safe, W=self.wire, d=self.display, key=self.key, state="ok",
                                 signer="ethereum", _lend=self.lend, _unload=self.unload,
                                 save=SimpleNamespace(load=Mock(return_value=None)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unsupported_states_disable_solana_without_changing_ethereum(self):
        unsupported = (
            ("ok", {"chip": "ATECC608"}, True, False, 240, 240),
            ("none", None, True, False, 240, 240),
            ("lock", self.key, True, False, 240, 240),
            ("ok", self.key, True, True, 240, 240),
            ("ok", self.key, False, False, 240, 240),
            ("ok", self.key, True, False, 128, 64),
            ("ok", self.key, True, False, 240, 128),
        )
        for state, key, sealed, opened, width, height in unsupported:
            with self.subTest(state=state, key=key, sealed=sealed, opened=opened, size=(width, height)):
                self.display.width = width
                self.display.height = height
                self.wire.SEALED = sealed
                self.wire.is_open.return_value = opened
                with patch.multiple(safe, key=key, state=state):
                    safe.handle({"id": 1, "type": "hello"})
                    hello = self.wire.send.call_args.args[0]
                    self.assertEqual(hello["solana_protocol"], 0)
                    self.assertEqual(hello["signer"], "ethereum" if state == "ok" else None)
                    for kind in ("sol_status", "sol_enroll", "sol_sign"):
                        safe.handle({"id": 2, "type": kind})
                        self.assertEqual(self.wire.send.call_args.args[0]["type"], "error")
        self.lend.assert_not_called()

    def test_supported_state_advertises_and_dispatches(self):
        safe.handle({"id": 1, "type": "hello"})
        self.assertEqual(self.wire.send.call_args.args[0]["solana_protocol"], 1)
        request = {"id": 2, "type": "sol_status"}
        with patch.dict(sys.modules, {"safe_sol": safe_sol}), patch.object(safe_sol, "handle") as handle:
            safe.handle(request)
        handle.assert_called_once_with(self.display, request, None)
        self.lend.assert_called_once_with()
        self.unload.assert_called_once_with()


class SolanaApproval(unittest.TestCase):
    def setUp(self):
        self.chip = Mock()
        self.chip.sign.return_value = (17, safe_sol._ORDER - 23)
        self.chip.metadata.return_value = {0xE0: b"\x03"}
        self.optiga = Mock(KEY3=0xE0F2, KEY4=0xE0F3)
        self.optiga.Chip.return_value = self.chip
        self.wire, self.saves = Mock(), Mock()
        self.review = Mock(return_value=True)
        patcher = patch.multiple(safe_sol, optiga=self.optiga, save=self.saves, wedgie=self.wire,
                                 _review=self.review)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.profile = {"network": "devnet", "swig": address(1), "wallet": address(2), "mint": address(3)}

    def transfer(self, kind):
        request = dict(self.profile, type="sol_sign", kind=kind, source=address(4), recipient=address(5),
                       amount=100_000, slot=123456, counter=1)
        args = [request["swig"], request["wallet"]]
        if kind == "token":
            args += [request["source"], request["mint"]]
        args += [request["recipient"], request["amount"], request["slot"], request["counter"]]
        digest = safe_sol.token_hash if kind == "token" else safe_sol.transfer_hash
        return dict(request, expected=digest(*args).hex())

    def test_mainnet_cannot_read_a_profile_prompt_or_open_the_chip(self):
        for kind in ("sol_status", "sol_enroll", "sol_sign"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "unknown Solana network"):
                safe_sol.handle(None, {"type": kind, "network": "mainnet"})
        self.saves.load.assert_not_called()
        self.review.assert_not_called()
        self.optiga.Chip.assert_not_called()

    def test_status_keeps_local_and_devnet_profiles_separate(self):
        local = dict(self.profile, network="local")
        for name, profile in (("solana_profile", local), ("solana_devnet_profile", self.profile)):
            self.saves.load.return_value = profile
            safe_sol.handle(None, {"id": 2, "type": "sol_status", "network": profile["network"]})
            self.saves.load.assert_called_with(name)
            self.wire.send.assert_called_with({"id": 2, "type": "sol_ok", "profile": profile})
        with self.assertRaisesRegex(ValueError, "another network"):
            safe_sol.handle(None, {"type": "sol_status", "network": "local"})
        self.optiga.Chip.assert_not_called()

    def test_enrollment_refuses_existing_devnet_key_and_occupied_slot(self):
        with patch.object(safe_sol, "_profile", return_value=self.profile):
            with self.assertRaisesRegex(ValueError, "fresh key"):
                safe_sol._enroll(None, {"existing_key": "04" + "11" * 64}, None)
            self.optiga.Chip.assert_not_called()
            with self.assertRaisesRegex(ValueError, "occupied"):
                safe_sol._enroll(None, {}, None)
        self.chip.genkey.assert_not_called()
        self.saves.store.assert_not_called()

    def test_unsigned_review_or_mismatched_transfer_never_signs(self):
        request = self.transfer("token")
        for changes in ({"network": "local"}, {"mint": address(7)}, {"recipient": address(6)},
                        {"source": self.profile["wallet"]}, {"kind": "token2022"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                safe_sol._sign(None, dict(request, **changes), self.profile)
        self.review.assert_not_called()
        self.review.return_value = False
        self.assertIsNone(safe_sol._sign(None, request, self.profile))
        self.optiga.Chip.assert_not_called()

    def test_approved_sol_and_spl_use_only_the_devnet_key(self):
        for kind in ("sol", "token"):
            request = self.transfer(kind)
            signed = safe_sol._sign(None, request, self.profile)
            self.chip.sign.assert_called_with(0xE0F2, hashlib.sha256(bytes.fromhex(request["expected"])).digest())
            self.assertEqual(signed, {"message": request["expected"], "signature": f"{17:064x}{23:064x}"})
        self.assertEqual(self.chip.close.call_count, 2)


if __name__ == "__main__":
    unittest.main()
