from typing import List

import webauthn
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
    AuthenticatorTransport,
)

from app.config import RP_ID, RP_NAME, RP_ORIGIN


def generate_registration_options(user_id: str, username: str, existing_credential_ids: List[bytes]):
    exclude = [
        PublicKeyCredentialDescriptor(id=cid)
        for cid in existing_credential_ids
    ]
    options = webauthn.generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=user_id.encode(),
        user_name=username,
        user_display_name=username,
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    return options


def verify_registration(challenge_bytes: bytes, credential_response: dict):
    return webauthn.verify_registration_response(
        credential=credential_response,
        expected_challenge=challenge_bytes,
        expected_rp_id=RP_ID,
        expected_origin=RP_ORIGIN,
        require_user_verification=False,
    )


def generate_authentication_options(credential_ids: List[bytes]):
    allow = [PublicKeyCredentialDescriptor(id=cid) for cid in credential_ids]
    options = webauthn.generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return options


def verify_authentication(challenge_bytes: bytes, credential_response: dict,
                          public_key: bytes, current_sign_count: int):
    return webauthn.verify_authentication_response(
        credential=credential_response,
        expected_challenge=challenge_bytes,
        expected_rp_id=RP_ID,
        expected_origin=RP_ORIGIN,
        credential_public_key=public_key,
        credential_current_sign_count=current_sign_count,
        require_user_verification=False,
    )
