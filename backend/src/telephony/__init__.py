"""Telephony / live transport (Sprint 8).

Live audio transports that carry a call to and from the voice pipeline behind the
provider-agnostic :class:`~src.telephony.transport.Transport` interface. The first
implementation is local microphone + speaker (:mod:`src.telephony.local_audio`);
LiveKit + SIP for a real phone number follows.
"""
