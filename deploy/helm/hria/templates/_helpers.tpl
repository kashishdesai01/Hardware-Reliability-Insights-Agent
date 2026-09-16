{{- define "hria.name" -}}hria{{- end }}
{{- define "hria.labels" -}}
app.kubernetes.io/name: {{ include "hria.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
{{- define "hria.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}{{ default "hria" .Values.serviceAccount.name }}{{ else }}default{{ end -}}
{{- end }}
