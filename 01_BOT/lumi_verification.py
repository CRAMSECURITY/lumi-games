"""Bind moderator decisions to a specific submitted verification, not an account."""
import re
import secrets


def new_review_id():
    return secrets.token_hex(12)


def parse_review_callback(data):
    prefix, choice, raw, review_id = data.split(':')
    if prefix != 'vcheck' or choice not in ('yes', 'no') or not re.fullmatch(r'[1-9][0-9]{0,18}', raw) or not re.fullmatch(r'[0-9a-f]{24}', review_id):
        raise ValueError('Invalid review callback')
    uid = int(raw)
    if uid > 2**63 - 1:
        raise ValueError('Invalid user ID')
    return uid, choice == 'yes', review_id


def decide_review(db, target, approved, actor, review_id):
    outcome = 'approved' if approved else 'rejected'
    result = db.execute("UPDATE verification_requests SET status=?,video_note_id=NULL,challenge=NULL,expires_at=NULL,review_id=NULL WHERE user_id=? AND status='review' AND review_id=? AND video_note_id IS NOT NULL AND EXISTS (SELECT 1 FROM profiles WHERE user_id=?)", (outcome, target, review_id, target))
    if not result.rowcount:
        return False
    db.execute("INSERT INTO profile_extras(user_id,verified,verification_status) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET verified=excluded.verified,verification_status=excluded.verification_status", (target,int(approved),outcome))
    db.execute("INSERT INTO security_audit(actor,action,target) VALUES (?,?,?)", (actor,'video_verify_approved' if approved else 'video_verify_rejected',target))
    return True
