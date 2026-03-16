from fastapi import HTTPException


GENDER_MAP = {
    "male": 1,
    "female": 2
}


def build_gender_targeting(gender_list):

    if not gender_list:
        return None

    gender_ids = []

    for gender in gender_list:

        gender_key = str(gender).lower()

        gender_id = GENDER_MAP.get(gender_key)

        if gender_id is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported gender: {gender}"
            )

        if gender_id not in gender_ids:
            gender_ids.append(gender_id)

    return gender_ids