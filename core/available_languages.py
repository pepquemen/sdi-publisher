"""
Languages offered in the "add language" dropdown.

A short, orientative list so the "+" dropdown isn't empty. It is NOT a
restriction: LibreTranslate's real language set depends on the models
installed on the user's own server, so this can be replaced at runtime by
querying GET /languages on their server.
"""

AVAILABLE_LANGUAGES = [
    ("bg", "Bulgarian"), ("ca", "Catalan"), ("cs", "Czech"), ("da", "Danish"),
    ("de", "German"), ("el", "Greek"), ("en", "English"), ("es", "Spanish"),
    ("et", "Estonian"), ("fi", "Finnish"), ("fr", "French"), ("hu", "Hungarian"),
    ("id", "Indonesian"), ("it", "Italian"), ("ja", "Japanese"), ("ko", "Korean"),
    ("lt", "Lithuanian"), ("lv", "Latvian"), ("nb", "Norwegian"), ("nl", "Dutch"),
    ("pl", "Polish"), ("pt", "Portuguese"), ("ro", "Romanian"), ("ru", "Russian"),
    ("sk", "Slovak"), ("sl", "Slovenian"), ("sv", "Swedish"), ("tr", "Turkish"),
    ("uk", "Ukrainian"), ("zh", "Chinese"),
]

_LABELS = dict(AVAILABLE_LANGUAGES)


def label_for(code):
    return _LABELS.get(code, code)
