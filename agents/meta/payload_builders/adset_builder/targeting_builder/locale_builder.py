from fastapi import HTTPException


def build_locale_targeting(locale_objects):

    if not locale_objects:
        return None

    locale_ids = []

    for locale in locale_objects:

        if not isinstance(locale, dict):
            raise HTTPException(
                status_code=400,
                detail="Locale must be an object"
            )

        locale_id = locale.get("id")

        if not locale_id:
            raise HTTPException(
                status_code=400,
                detail="Locale missing id"
            )

        if locale_id not in locale_ids:
            locale_ids.append(int(locale_id))

    return locale_ids