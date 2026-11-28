"""Small allowlisted localization pilot; never changes authorization or profile data."""
from types import MappingProxyType

RU = MappingProxyType(dict(title='LUMI · Клубы по интересам', mine='Мои клубы: ', none='нет', pilot='Пилот: пока без общих чатов и списка участников.', join='Вступить · ', leave='Выйти · ', weekly='Активности недели', unavailable='Клубы недоступны.', account='Клубы недоступны для этого аккаунта.', reopen='Открой /clubs заново.', joined='Ты вступил в клуб', left='Ты покинул клуб', owned='Уже в клубе', limit='Максимум 3 клуба', full='Клуб заполнен', activity_unavailable='Активности недоступны.', activity_title='LUMI · Активности недели (UTC)', private='Отметки личные, без наград и проверки выполнения.', done=' · выполнено', mark='Выполнено · ', empty='Вступи в клуб через /clubs.', games='Игры', music='Музыка', travel='Путешествия', art='Творчество', task_games='Поделись любимой игрой в разговоре с другом', task_music='Обсуди любимую песню с другом', task_travel='Обсуди город мечты с другом', task_art='Поделись творческой идеей с другом'))
EN = MappingProxyType(dict(title='LUMI · Interest clubs', mine='My clubs: ', none='none', pilot='Pilot: no group chats or member lists yet.', join='Join · ', leave='Leave · ', weekly='Weekly activities', unavailable='Clubs are unavailable.', account='Clubs are unavailable for this account.', reopen='Open /clubs again.', joined='You joined the club', left='You left the club', owned='Already a member', limit='Maximum 3 clubs', full='Club is full', activity_unavailable='Activities are unavailable.', activity_title='LUMI · Weekly activities (UTC)', private='Completion marks are private, with no rewards or verification.', done=' · completed', mark='Completed · ', empty='Join a club via /clubs.', games='Gaming', music='Music', travel='Travel', art='Art', task_games='Talk to a friend about your favorite game', task_music='Discuss your favorite song with a friend', task_travel='Discuss your dream city with a friend', task_art='Share a creative idea with a friend'))

def language(code):
    if isinstance(code, str) and len(code) <= 35 and code.lower().replace('_', '-').split('-')[0] == 'en':
        return 'en'
    return 'ru'

def strings(code=None):
    return EN if language(code) == 'en' else RU
