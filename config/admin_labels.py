from __future__ import annotations

from accounts.models import (
    DataPrivacyRequest,
    ExternalIdentity,
    LegalDocumentVersion,
    NotificationDispatch,
    NotificationEvent,
    NotificationPreference,
    Profile,
    PushDevice,
    UserLegalAcceptance,
)
from annotations.models import Annotation
from caselaw.models import CaseLaw
from community.models import (
    Category,
    Comment,
    ModerationConfig,
    Post,
    Report,
    ReportModerationAction,
    UserModerationEvent,
    UserModerationStatus,
)
from courses.models import CourseAsset, CoursePost, LiveEvent
from entitlements.models import Entitlement, Subscription
from library.models import Book, BookChapter, BookVersion
from templates_bank.models import TemplatePiece


def _set_model_labels(model, singular: str, plural: str) -> None:
    model._meta.verbose_name = singular
    model._meta.verbose_name_plural = plural


def _set_field_labels(model, labels: dict[str, str]) -> None:
    for field_name, label in labels.items():
        model._meta.get_field(field_name).verbose_name = label


def _set_choice_labels(model, field_name: str, labels: dict[str, str]) -> None:
    field = model._meta.get_field(field_name)
    field.choices = [
        (value, labels.get(value, label))
        for value, label in list(field.choices)
    ]


def install_admin_labels() -> None:
    if getattr(install_admin_labels, '_lv_admin_labels_installed', False):
        return

    _set_model_labels(Book, 'livro', 'livros')
    _set_field_labels(
        Book,
        {
            'title': 'Título',
            'description': 'Descrição',
            'status': 'Status',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )
    _set_choice_labels(Book, 'status', {'draft': 'Rascunho', 'published': 'Publicado', 'archived': 'Arquivado'})

    _set_model_labels(BookVersion, 'versão do livro', 'versões do livro')
    _set_field_labels(
        BookVersion,
        {
            'book': 'Livro',
            'version': 'Versão',
            'published_at': 'Publicado em',
            'changelog': 'Registro de alterações',
            'status': 'Status',
            'created_at': 'Criado em',
        },
    )
    _set_choice_labels(BookVersion, 'status', {'draft': 'Rascunho', 'published': 'Publicado', 'archived': 'Arquivado'})

    _set_model_labels(BookChapter, 'capítulo', 'capítulos')
    _set_field_labels(
        BookChapter,
        {
            'book_version': 'Versão do livro',
            'title': 'Título',
            'slug': 'Slug',
            'order': 'Ordem',
            'content_rich': 'Conteúdo',
            'content_plain': 'Texto puro',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )

    _set_model_labels(CoursePost, 'post do curso', 'posts do curso')
    _set_field_labels(
        CoursePost,
        {
            'title': 'Título',
            'slug': 'Slug',
            'author_name': 'Autor',
            'excerpt': 'Resumo',
            'content_rich': 'Conteúdo',
            'content_plain': 'Texto puro',
            'post_type': 'Tipo de post',
            'tags': 'Tags',
            'status': 'Status',
            'published_at': 'Publicado em',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )
    _set_choice_labels(CoursePost, 'post_type', {'blog': 'Artigo', 'lesson': 'Aula', 'announcement': 'Aviso'})
    _set_choice_labels(CoursePost, 'status', {'draft': 'Rascunho', 'published': 'Publicado', 'archived': 'Arquivado'})

    _set_model_labels(CourseAsset, 'material de curso', 'materiais de curso')
    _set_field_labels(
        CourseAsset,
        {
            'post': 'Post do curso',
            'title': 'Título',
            'description': 'Descrição',
            'asset_type': 'Tipo de material',
            'file_url': 'URL do arquivo',
            'tags': 'Tags',
            'status': 'Status',
            'published_at': 'Publicado em',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )
    _set_choice_labels(
        CourseAsset,
        'asset_type',
        {
            'pdf': 'PDF',
            'checklist': 'Checklist',
            'model': 'Modelo',
            'video': 'Vídeo',
            'link': 'Link',
            'other': 'Outro',
        },
    )
    _set_choice_labels(CourseAsset, 'status', {'draft': 'Rascunho', 'published': 'Publicado', 'archived': 'Arquivado'})

    _set_model_labels(LiveEvent, 'live ou evento', 'lives e eventos')
    _set_field_labels(
        LiveEvent,
        {
            'post': 'Post do curso',
            'title': 'Título',
            'description': 'Descrição',
            'event_type': 'Tipo de evento',
            'status': 'Status',
            'starts_at': 'Início',
            'ends_at': 'Fim',
            'meeting_url': 'URL da reunião',
            'recording_url': 'URL da gravação',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )
    _set_choice_labels(
        LiveEvent,
        'event_type',
        {'live_class': 'Aula ao vivo', 'mentoring': 'Mentoria', 'webinar': 'Webinário'},
    )
    _set_choice_labels(
        LiveEvent,
        'status',
        {
            'draft': 'Rascunho',
            'scheduled': 'Agendada',
            'live': 'Ao vivo',
            'finished': 'Encerrada',
            'canceled': 'Cancelada',
        },
    )

    _set_model_labels(Profile, 'perfil de usuário', 'perfis de usuários')
    _set_field_labels(
        Profile,
        {
            'user': 'Usuário',
            'full_name': 'Nome completo',
            'profession': 'Profissão',
            'avatar': 'Avatar',
            'avatar_url': 'URL do avatar',
            'role': 'Perfil de acesso',
        },
    )

    _set_model_labels(DataPrivacyRequest, 'solicitação de privacidade', 'solicitações de privacidade')
    _set_field_labels(
        DataPrivacyRequest,
        {
            'user': 'Usuário',
            'request_type': 'Tipo de solicitação',
            'status': 'Status',
            'retention_policy': 'Política de retenção',
            'payload': 'Dados da solicitação',
            'created_at': 'Criado em',
            'processed_at': 'Processado em',
        },
    )
    _set_choice_labels(DataPrivacyRequest, 'request_type', {'export': 'Exportação', 'erasure': 'Eliminação'})
    _set_choice_labels(DataPrivacyRequest, 'status', {'requested': 'Solicitada', 'completed': 'Concluída', 'failed': 'Falhou'})

    _set_model_labels(ExternalIdentity, 'identidade externa', 'identidades externas')
    _set_field_labels(
        ExternalIdentity,
        {
            'user': 'Usuário',
            'provider': 'Provedor',
            'provider_subject': 'ID do provedor',
            'email': 'E-mail do provedor',
            'email_verified': 'E-mail verificado',
            'display_name': 'Nome exibido',
            'avatar_url': 'URL do avatar',
            'linked_at': 'Vinculada em',
            'last_login_at': 'Último login social',
            'last_synced_at': 'Última sincronização',
            'provider_claims': 'Claims do provedor',
        },
    )
    _set_choice_labels(ExternalIdentity, 'provider', {'google': 'Google', 'linkedin': 'LinkedIn'})

    _set_model_labels(LegalDocumentVersion, 'documento legal', 'documentos legais')
    _set_field_labels(
        LegalDocumentVersion,
        {
            'document_type': 'Tipo de documento',
            'version': 'Versão',
            'title': 'Título',
            'content_html': 'Conteúdo HTML',
            'content_sha256': 'Hash SHA-256',
            'is_active': 'Versão ativa',
            'published_at': 'Publicado em',
            'enforcement_starts_at': 'Exigência inicia em',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )
    _set_choice_labels(
        LegalDocumentVersion,
        'document_type',
        {
            'terms_of_use': 'Termos de uso',
            'privacy_policy': 'Política de privacidade',
        },
    )

    _set_model_labels(UserLegalAcceptance, 'aceite legal', 'aceites legais')
    _set_field_labels(
        UserLegalAcceptance,
        {
            'user': 'Usuário',
            'document': 'Documento',
            'accepted_at': 'Aceito em',
            'source': 'Origem',
            'app_platform': 'Plataforma',
            'app_version': 'Versão do app',
            'ip_address': 'Endereço IP',
            'user_agent': 'User agent',
        },
    )
    _set_choice_labels(
        UserLegalAcceptance,
        'source',
        {
            'login_gate': 'Barreira de aceite',
            'account_settings': 'Minha conta',
            'admin': 'Admin',
        },
    )
    _set_choice_labels(
        UserLegalAcceptance,
        'app_platform',
        {
            'web': 'Web',
            'android': 'Android',
            'ios': 'iOS',
            'system': 'Sistema',
        },
    )

    _set_model_labels(NotificationPreference, 'preferência de notificação', 'preferências de notificação')
    _set_field_labels(
        NotificationPreference,
        {
            'user': 'Usuário',
            'notifications_enabled': 'Notificações habilitadas',
            'book_version_updates_enabled': 'Atualizações de versões de livros',
            'new_content_updates_enabled': 'Novos conteúdos',
            'community_interaction_updates_enabled': 'Interações da comunidade',
            'push_enabled': 'Push habilitado',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )

    _set_model_labels(NotificationEvent, 'evento de notificação', 'eventos de notificação')
    _set_field_labels(
        NotificationEvent,
        {
            'event_type': 'Tipo de evento',
            'dedup_key': 'Chave de deduplicação',
            'title': 'Título',
            'body': 'Mensagem',
            'payload': 'Dados do evento',
            'created_at': 'Criado em',
        },
    )
    _set_choice_labels(
        NotificationEvent,
        'event_type',
        {
            'book_version_published': 'Nova versão de livro publicada',
            'content_published': 'Novo conteúdo publicado',
            'course_content_published': 'Novo conteúdo do curso publicado',
            'caselaw_published': 'Nova jurisprudência publicada',
            'community_interaction': 'Interação na comunidade',
        },
    )

    _set_model_labels(NotificationDispatch, 'envio de notificação', 'envios de notificação')
    _set_field_labels(
        NotificationDispatch,
        {
            'event': 'Evento',
            'user': 'Usuário',
            'channel': 'Canal',
            'status': 'Status',
            'reason': 'Motivo',
            'dispatched_at': 'Enviado em',
            'acknowledged_at': 'Confirmado em',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )
    _set_choice_labels(NotificationDispatch, 'channel', {'push': 'Push', 'in_app': 'No app'})
    _set_choice_labels(NotificationDispatch, 'status', {'pending': 'Pendente', 'skipped': 'Ignorado', 'sent': 'Enviado', 'failed': 'Falhou'})

    _set_model_labels(PushDevice, 'dispositivo push', 'dispositivos push')
    _set_field_labels(
        PushDevice,
        {
            'user': 'Usuário',
            'platform': 'Plataforma',
            'installation_id': 'Identidade da instalação',
            'expo_push_token': 'Token Expo',
            'is_active': 'Ativo',
            'last_seen_at': 'Última atividade',
            'disabled_reason': 'Motivo da desativação',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )

    _set_model_labels(Category, 'categoria da comunidade', 'categorias da comunidade')
    _set_field_labels(
        Category,
        {
            'name': 'Nome',
            'slug': 'Slug',
            'description': 'Descrição',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )

    _set_model_labels(Post, 'post da comunidade', 'posts da comunidade')
    _set_field_labels(
        Post,
        {
            'author': 'Autor',
            'category': 'Categoria',
            'title': 'Título',
            'body': 'Conteúdo',
            'moderation_state': 'Estado da moderação',
            'moderated_by': 'Moderado por',
            'moderated_at': 'Moderado em',
            'moderation_note': 'Justificativa da moderação',
            'likes_count': 'Curtidas',
            'comments_count': 'Comentários',
            'last_comment_at': 'Último comentário em',
            'last_activity_at': 'Última atividade em',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )
    _set_choice_labels(Post, 'moderation_state', {'active': 'Ativo', 'under_review': 'Em análise', 'removed': 'Removido'})

    _set_model_labels(Comment, 'comentário da comunidade', 'comentários da comunidade')
    _set_field_labels(
        Comment,
        {
            'post': 'Post',
            'author': 'Autor',
            'body': 'Conteúdo',
            'moderation_state': 'Estado da moderação',
            'moderated_by': 'Moderado por',
            'moderated_at': 'Moderado em',
            'moderation_note': 'Justificativa da moderação',
            'likes_count': 'Curtidas',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )
    _set_choice_labels(Comment, 'moderation_state', {'active': 'Ativo', 'under_review': 'Em análise', 'removed': 'Removido'})

    _set_model_labels(Report, 'denúncia', 'denúncias')
    _set_field_labels(
        Report,
        {
            'reporter': 'Denunciante',
            'post': 'Post',
            'comment': 'Comentário',
            'reason': 'Motivo da denúncia',
            'status': 'Status',
            'priority': 'Prioridade',
            'decision': 'Decisão',
            'assigned_moderator': 'Moderador responsável',
            'moderated_by': 'Moderado por',
            'moderated_at': 'Moderado em',
            'moderation_note': 'Justificativa da moderação',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )
    _set_choice_labels(Report, 'status', {'open': 'Aberta', 'in_review': 'Em análise', 'resolved': 'Resolvida', 'escalated': 'Escalada', 'rejected': 'Rejeitada'})
    _set_choice_labels(Report, 'priority', {'low': 'Baixa', 'medium': 'Média', 'high': 'Alta', 'critical': 'Crítica'})
    _set_choice_labels(Report, 'decision', {'approve': 'Aprovar', 'remove': 'Remover', 'escalate': 'Escalar', 'reject': 'Rejeitar'})

    _set_model_labels(ReportModerationAction, 'ação de moderação', 'ações de moderação')
    _set_field_labels(
        ReportModerationAction,
        {
            'report': 'Denúncia',
            'actor': 'Responsável',
            'action_type': 'Tipo de ação',
            'from_status': 'Status anterior',
            'to_status': 'Novo status',
            'from_priority': 'Prioridade anterior',
            'to_priority': 'Nova prioridade',
            'decision': 'Decisão',
            'note': 'Observação',
            'created_at': 'Criado em',
        },
    )
    _set_choice_labels(
        ReportModerationAction,
        'action_type',
        {
            'status_changed': 'Status alterado',
            'approved': 'Aprovada',
            'removed': 'Removida',
            'escalated': 'Escalada',
            'rejected': 'Rejeitada',
            'priority_changed': 'Prioridade alterada',
            'assigned': 'Atribuída',
        },
    )

    _set_model_labels(ModerationConfig, 'configuração de moderação', 'configurações de moderação')
    _set_field_labels(
        ModerationConfig,
        {
            'singleton_key': 'Chave única',
            'reports_per_warning': 'Denúncias por aviso',
            'max_warnings_before_ban': 'Máximo de avisos antes do banimento',
            'auto_ban_on_threshold': 'Banimento automático ao atingir o limite',
            'ban_scope': 'Escopo do banimento',
            'warning_message_template': 'Mensagem de aviso',
            'ban_message_template': 'Mensagem de banimento',
            'updated_at': 'Atualizado em',
        },
    )
    _set_choice_labels(ModerationConfig, 'ban_scope', {'community_only': 'Apenas comunidade', 'app_wide': 'Aplicativo inteiro'})

    _set_model_labels(UserModerationStatus, 'status de moderação do usuário', 'status de moderação dos usuários')
    _set_field_labels(
        UserModerationStatus,
        {
            'user': 'Usuário',
            'warnings_issued': 'Avisos emitidos',
            'last_warning_at': 'Último aviso em',
            'is_banned': 'Banido',
            'ban_scope': 'Escopo do banimento',
            'banned_at': 'Banido em',
            'banned_by': 'Banido por',
            'ban_reason': 'Motivo do banimento',
            'pending_login_message': 'Mensagem pendente no login',
            'pending_login_message_level': 'Nível da mensagem',
            'pending_login_message_created_at': 'Mensagem criada em',
            'updated_at': 'Atualizado em',
        },
    )
    _set_choice_labels(UserModerationStatus, 'ban_scope', {'community_only': 'Apenas comunidade', 'app_wide': 'Aplicativo inteiro'})
    _set_choice_labels(UserModerationStatus, 'pending_login_message_level', {'info': 'Informativo', 'warning': 'Atenção', 'danger': 'Crítico'})

    _set_model_labels(UserModerationEvent, 'evento de moderação do usuário', 'eventos de moderação do usuário')
    _set_field_labels(
        UserModerationEvent,
        {
            'user': 'Usuário',
            'actor': 'Responsável',
            'report': 'Denúncia',
            'action_type': 'Tipo de ação',
            'warning_number': 'Número do aviso',
            'removed_reports_total': 'Denúncias removidas',
            'note': 'Observação',
            'created_at': 'Criado em',
        },
    )
    _set_choice_labels(
        UserModerationEvent,
        'action_type',
        {'warning_issued': 'Aviso emitido', 'ban_applied': 'Banimento aplicado', 'ban_revoked': 'Banimento revogado'},
    )

    _set_model_labels(Subscription, 'assinatura', 'assinaturas')
    _set_field_labels(
        Subscription,
        {
            'user': 'Usuário',
            'tier': 'Plano',
            'status': 'Status',
            'is_founder': 'Fundador',
            'started_at': 'Início',
            'expires_at': 'Expira em',
            'source': 'Origem',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )

    _set_model_labels(Entitlement, 'direito de acesso', 'direitos de acesso')
    _set_field_labels(
        Entitlement,
        {
            'user': 'Usuário',
            'book': 'Livro',
            'subscription': 'Assinatura',
            'product': 'Produto',
            'status': 'Status',
            'expires_at': 'Expira em',
            'source': 'Origem',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )

    _set_model_labels(Annotation, 'anotação de leitura', 'anotações de leitura')
    _set_field_labels(
        Annotation,
        {
            'user': 'Usuário',
            'book_version': 'Versão do livro',
            'chapter': 'Capítulo',
            'selector': 'Seletor',
            'start_offset': 'Início do trecho',
            'end_offset': 'Fim do trecho',
            'excerpt': 'Trecho destacado',
            'note': 'Anotação',
            'color': 'Cor',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )

    _set_model_labels(CaseLaw, 'jurisprudência', 'jurisprudências')
    _set_field_labels(
        CaseLaw,
        {
            'court': 'Tribunal',
            'case_number': 'Número do processo',
            'decision_date': 'Data da decisão',
            'ementa_rich': 'Ementa',
            'ementa_plain': 'Ementa em texto',
            'url': 'URL da decisão',
            'anchors': 'Âncoras',
            'tags': 'Tags',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )

    _set_model_labels(TemplatePiece, 'peça jurídica', 'peças jurídicas')
    _set_field_labels(
        TemplatePiece,
        {
            'title': 'Título',
            'slug': 'Slug',
            'template_code': 'Código da peça',
            'version': 'Versão',
            'changelog': 'Registro de alterações',
            'description': 'Descrição',
            'category': 'Categoria',
            'tags': 'Tags',
            'file_url': 'URL do arquivo',
            'file_upload': 'Arquivo enviado',
            'file_name': 'Nome do arquivo',
            'file_mime_type': 'Tipo MIME',
            'file_size_bytes': 'Tamanho do arquivo (bytes)',
            'file_sha256': 'Hash SHA-256',
            'status': 'Status',
            'published_at': 'Publicado em',
            'created_at': 'Criado em',
            'updated_at': 'Atualizado em',
        },
    )
    _set_choice_labels(
        TemplatePiece,
        'category',
        {
            'petition': 'Petição',
            'contract': 'Contrato',
            'appeal': 'Recurso',
            'motion': 'Petição intermediária',
            'administrative': 'Administrativo',
            'other': 'Outro',
        },
    )
    _set_choice_labels(TemplatePiece, 'status', {'draft': 'Rascunho', 'published': 'Publicado', 'archived': 'Arquivado'})

    install_admin_labels._lv_admin_labels_installed = True
