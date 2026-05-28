

class HarvestKeyDB(UserDB):
    """Accept all public-key auth and append new keys to authorized_keys."""

    def checkKey(self, theusername: str, key, src_ip: str) -> bool:
        try:
            key_line: str = key.toString("openssh").decode("utf-8").strip()
        except Exception:
            return super().checkKey(theusername, key, src_ip)

        etc_path = CowrieConfig.get("honeypot", "etc_path", fallback="etc")
        auth_keys_path = Path(etc_path) / "authorized_keys"

        try:
            if not self._key_known(auth_keys_path, key_line):
                with auth_keys_path.open("a", newline="\n", encoding="utf-8") as f:
                    f.write(key_line + "\n")
                log.msg(
                    f"eventid=cowrie.auth.keyHarvested "
                    f"src_ip={src_ip} username={theusername} "
                    f"key_type={key.sshType().decode('ascii', errors='replace')}"
                )
        except OSError as exc:
            log.err(f"HarvestKeyDB: could not write to {auth_keys_path}: {exc}")

        return True

    @staticmethod
    def _key_known(auth_keys_path: Path, key_line: str) -> bool:
        """True if the same key material (type + blob) is already in the file."""
        if not auth_keys_path.exists():
            return False
        parts = key_line.split()
        if len(parts) < 2:
            return False
        key_id = f"{parts[0]} {parts[1]}"
        with auth_keys_path.open(encoding="utf-8") as f:
            return any(line.strip().startswith(key_id) for line in f)
