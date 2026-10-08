"""Password policy (OWASP ASVS 2.1): length 12-1024, any characters, no composition rules, and refuse
passwords that are common, repetitive or built from the product name."""

import re

# A short list of the most common passwords that pass the length rule (breach corpora top entries).
COMMON = frozenset(
    {
        "123456789012",
        "1234567890123",
        "12345678910",
        "123456789123",
        "qwertyuiopas",
        "qwertyuiop123",
        "password1234",
        "password12345",
        "passwordpassword",
        "iloveyou1234",
        "abcdefghijkl",
        "abc123abc123",
        "aaaaaaaaaaaa",
        "111111111111",
        "000000000000",
        "letmein12345",
        "welcome12345",
        "administrator",
        "admin1234567",
        "changeme1234",
        "changemeplease",
        "qwerty123456",
        "1q2w3e4r5t6y",
        "zaq12wsxcde3",
        "football1234",
        "baseball1234",
        "superman1234",
        "monkey123456",
        "sunshine1234",
        "princess1234",
        "trustno11234",
        "dragon123456",
        "master123456",
        "correcthorse",
        "correct horse battery",
    }
)
_REPEAT = re.compile(r"^(.{1,3})\1+$")


def password_problem(password: str, *, email: str | None = None) -> str | None:
    """Return why a password is refused, or None."""
    lowered = password.lower()
    if lowered in COMMON or lowered.rstrip("!.1") in COMMON:
        return "this password is too common; choose another"
    if _REPEAT.match(password):
        return "this password is too repetitive"
    if "glasshaus" in lowered and len(lowered.replace("glasshaus", "")) < 8:
        return "do not base the password on the product name"
    if email:
        local = email.split("@")[0].lower()
        if len(local) >= 4 and local in lowered and len(lowered.replace(local, "")) < 8:
            return "do not base the password on your email address"
    return None
