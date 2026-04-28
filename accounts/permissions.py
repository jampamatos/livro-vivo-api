from rest_framework.permissions import BasePermission

from .legal import LegalAcceptanceRequired, build_legal_acceptance_required_payload


class HasAcceptedRequiredLegalDocuments(BasePermission):
    message = 'Aceite os documentos legais vigentes para continuar usando o beta.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        required_documents = build_legal_acceptance_required_payload(user, request=request)
        if required_documents:
            raise LegalAcceptanceRequired(
                required_documents=required_documents,
                message=self.message,
            )
        return True
