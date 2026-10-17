# Safe Signer

A [wedgie](https://wedgie.dev) app: sign [Safe{Wallet}](https://app.safe.global) transactions with a key
that lives in the wedgie's secure chip: an ATECC608 or an OPTIGA Trust M.

- **The key: yours, made once, locked for good.** First start: press A, and the chip makes a P-256 key.
  It never leaves the chip.
  - **Trust M** (`safe_key.py`): the key goes in slot KEY2 (replacing an unlocked one) and its public key
    in DATA[11], then both are locked (lifecycle operational). After that nothing can replace the key,
    change its public key or unlock them: no app, no computer, no one. Every start reads the public key
    from the chip and checks it with a fresh signature; the Pico keeps nothing that matters. A chip whose
    KEY2 is already locked with a key that isn't Safe Signer's shows **Swap the chip** and never signs.
    A key from safe-12 or older (unlocked, its public key only in the save) asks **Lock this key?** once:
    yes keeps it for good, no makes your own. Other apps use KEY3 and KEY4.
  - **ATECC608** (slot 0): A writes and locks its config (`atecc.CONFIG`) and locks its data zone if that
    isn't done yet, makes the key in slot 0, then locks slot 0. After that nothing can replace the key; the
    chip works its public key out every start. Other slots stay free for other apps. A chip whose config
    sets slot 0 up some other way shows **Swap the chip**. A safe-12 key (unlocked, saved) asks
    **Lock this key?** the same way.
- **On chain.** The key becomes a Safe owner through Safe's passkey signer
  (`SafeWebAuthnSignerFactory.createSigner(x, y, verifiers)`, safe-modules passkey v0.2.1). That signer's
  address is the wedgie's Safe owner address, the same on every chain: the home screen shows it
  (`safe_addr.py` works it out, once per key), and [wedgie.dev/safe](https://wedgie.dev/safe) shows the
  same one. Needs a chain with the P-256 precompile (Base, Optimism, Arbitrum, Ethereum).
- **wedgie.dev/safe** makes a new Safe with the wedgie as an owner, adds it to a Safe you already own
  (from a browser wallet that is an owner), and signs and executes transactions.
- **Execute on wedgie.dev/safe, not Safe{Wallet}.** Safe{Wallet} can't execute a transaction a wedgie
  signed: it fails with GS021 ([Safe's bug](https://github.com/safe-global/safe-wallet-monorepo/issues/8808)).
  Signing there is fine.
- **Signing.** The computer sends the transaction's fields. The wedgie works out the Safe tx hash
  itself, shows what it can decode (to, amount, owner changes), and signs only when you press A on it.
  Calls it cannot decode refuse. Y, or no answer in 2 minutes, is a no.
  Amounts are big. Address pages use blockies (the same 8x8 pattern wallets draw, `safe_blockie.py`;
  colors are the nearest of the wedgie's 16). The footer blockie identifies the Safe address, not the
  transaction hash. It cannot detect a changed transaction for the same Safe.
  Every page is a few plain words. Supported actions include a send, an owner change,
  a limit change, a swap (its exact approval folds in). The relay's fee (up to 1 USDC or 0.001 ETH) is a
  small line on that page; a bigger one keeps its own page. First-time limit setup keeps the
  amounts and key permissions on separate pages. Role assignments show the full role key.
  Warnings are red. The reading code (`safe_read.py`) loads only while a
  question is up.
  Every page shows which Safe: its blockie, the chain, its address.
- **What it won't take on trust.** It refuses DELEGATECALLs except a nonempty Safe MultiSend batch.
  It also refuses DELEGATECALLs inside that batch. "Daily limit" pages only for this Safe's own Roles (its CREATE2
  address, worked out on the wedgie); any other contract with the same calls is "Unknown". An unlimited
  approval says "ALL USDC", red. Unrecognized calls, unknown router calls and unreadable conditions
  refuse before signing. LI.FI routes refuse until the app can show their full route effects. A
  button press made before a page is up doesn't answer it.
- **Supported reviews.** Signing needs a 240x240 display. Small OLED displays cannot show these pages,
  so signing refuses them. A role assignment must change one membership. An allowance must have equal
  initial balance, refill cap and refill amount, with a one-day refill period. Other shapes refuse.
  A function permission that allows delegatecall also refuses.
- **Trust boundary.** A non-exportable key does not prove that the firmware is genuine. Installed apps
  and replacement firmware can access the chip. These review checks protect the normal signing path,
  not a device that runs hostile code. Do not treat a chip authenticity check as firmware attestation.
- **No PIN or biometric.** Safe Signer sets the WebAuthn user-verification flag because Safe's standard
  passkey signer requires it. The app does not perform user verification. The wedgie's green button is
  a physical-presence check only. Anyone who has the device can approve after pressing it. Do not treat
  this key as protected by a PIN or biometric.

## Controls

- A: make the key (first start) / lock a key from before / sign
- Y: no

## USB

One JSON line each way. Anything else goes to the wedgie firmware as usual.

```
{"id":1,"type":"safe_sign","tx":{"chainId":8453,"safe":"0x..","to":"0x..","value":"0","data":"0x",
 "operation":0,"safeTxGas":0,"baseGas":0,"gasPrice":0,"gasToken":"0x0..","refundReceiver":"0x0..","nonce":0}}
-> {"id":1,"type":"safe_sig","safeTxHash":"0x..","x":"0x..","y":"0x..","r":"0x..","s":"0x..",
    "authenticatorData":"0x..","clientDataFields":"\"origin\":\"https://wedgie.dev\""}
-> {"id":1,"type":"refused"}
```

`hello` also returns `"safe": {"x", "y", "chip"}` (null until there's a key it signs with), `"signer"` (its Safe
owner address, as the home screen shows it), `"safe_state"` (`"ok"`, `"none"` no key yet, `"lock"` a key from
before waiting for its lock, `"swap"` a chip locked with someone else's key) and `"safe_chunk": 4000`.

The wedgie keeps a list of its Safes (save `safes`, at most 32, newest first) so any computer can list
them. Signing for a Safe adds it; a host that made or opened one adds it with `safe_note`:

```
{"id":5,"type":"safe_list"}                                   -> {"id":5,"type":"safe_list","safes":["8453:0x..", ...]}
{"id":6,"type":"safe_note","chainId":8453,"safe":"0x.."}      -> {"id":6,"type":"ok","safes":3}
```

It's only a list of addresses: wedgie.dev/safe checks on chain that the wedgie is an owner before showing one.

A USB line is at most 6 KB. A bigger transaction (a bridge swap's calldata) sends its data ahead in
pieces of up to `safe_chunk` hex characters, then `safe_sign` with `"data": "@"`:

```
{"id":2,"type":"safe_data","at":0,"hex":"8d80ff0a..."}     -> {"id":2,"type":"safe_data","have":2000}
{"id":3,"type":"safe_data","at":2000,"hex":"..."}          -> {"id":3,"type":"safe_data","have":3900}
{"id":4,"type":"safe_sign","tx":{..., "data":"@"}}
```

`at` = bytes sent so far (0 starts over). At most 8000 bytes of data (more answers `too big`: joining
the pieces needs one block that size, and a used RP2040 heap doesn't always have a bigger one). The wedgie hashes what it was given, so the host still checks
the `safeTxHash` it gets back.

What it reads in plain words: ETH and token sends, owner and threshold changes, modules on and off, the
7-day recovery module (Candide: guardians, cancel), Instant Wallet's daily budget (Zodiac Roles), exact
approvals, and decoded Uniswap swaps (pay, minimum back, who gets paid). Unreadable calls refuse before
signing. LI.FI routes are not yet fully decoded and refuse.

The Safe signature for this owner is a contract signature (`v = 0`): `r` = the signer contract,
`s` = offset of the dynamic part, which holds `abi.encode(authenticatorData, clientDataFields, r, s)`.

## Saves

- `key`: only a safe-12 key's public key (x, y), to offer to lock it; dropped once it's locked or replaced.
  The chip keeps the key and its public key.
- `signer`: the Safe owner address worked out from `key` (made again if it's missing).
- `safes`: the Safes it's in (`"<chainId>:<address>"`), for wedgie.dev/safe's list. Making a new key clears it.

## Checks

Run `scripts/smoke.sh` with `uv` and an existing local Python interpreter. It uses no network, device or
private key. It exercises the real USB signing handler with display, buttons and chip stand-ins.
It is not a firmware or cryptographic hardware test.

Before release, run wedgie-dev's `node tools/safechip.mjs --app <this-checkout>` on the virtual RP2040.
Then check the exact app and firmware on a real board. Do not use an unverified build to hold funds.

MIT
