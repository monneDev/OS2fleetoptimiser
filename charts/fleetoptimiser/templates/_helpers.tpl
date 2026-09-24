{{- define "fleetoptimiser.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "fleetoptimiser.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "fleetoptimiser.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "fleetoptimiser.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "fleetoptimiser.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "fleetoptimiser.selectorLabels" -}}
app.kubernetes.io/name: {{ include "fleetoptimiser.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "fleetoptimiser.componentSelectorLabels" -}}
{{ include "fleetoptimiser.selectorLabels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "fleetoptimiser.backendImage" -}}
{{- printf "%s:%s" .Values.backend.image.repository (.Values.backend.image.tag | default .Chart.AppVersion) }}
{{- end }}

{{- define "fleetoptimiser.runtimeEnv" -}}
- name: DB_SERVER
  value: {{ required "runtime.database.server is required" .Values.runtime.database.server | quote }}
- name: DB_URL
  value: {{ required "runtime.database.host is required" .Values.runtime.database.host | quote }}
- name: DB_NAME
  value: {{ required "runtime.database.name is required" .Values.runtime.database.name | quote }}
- name: DB_USER
  value: {{ required "runtime.database.user is required" .Values.runtime.database.user | quote }}
- name: DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ required "runtime.database.passwordSecret.name is required" .Values.runtime.database.passwordSecret.name }}
      key: {{ required "runtime.database.passwordSecret.key is required" .Values.runtime.database.passwordSecret.key }}
- name: DB_POOL_SIZE
  value: {{ .Values.runtime.database.poolSize | quote }}
- name: DB_MAX_OVERFLOW
  value: {{ .Values.runtime.database.maxOverflow | quote }}
- name: DB_POOL_TIMEOUT
  value: {{ .Values.runtime.database.poolTimeout | quote }}
- name: DB_POOL_PRE_PING
  value: {{ .Values.runtime.database.poolPrePing | quote }}
- name: RABBITMQ_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ required "runtime.rabbitmq.passwordSecret.name is required" .Values.runtime.rabbitmq.passwordSecret.name }}
      key: {{ required "runtime.rabbitmq.passwordSecret.key is required" .Values.runtime.rabbitmq.passwordSecret.key }}
- name: VALKEY_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ required "runtime.valkey.passwordSecret.name is required" .Values.runtime.valkey.passwordSecret.name }}
      key: {{ required "runtime.valkey.passwordSecret.key is required" .Values.runtime.valkey.passwordSecret.key }}
- name: CELERY_QUEUE
  value: {{ .Values.runtime.celery.queue | quote }}
- name: TTL
  value: {{ .Values.runtime.celery.resultTtlDays | quote }}
- name: SEED_DUMMY_DATA
  value: {{ .Values.runtime.seedDummyData | quote }}
{{- end }}

{{- define "fleetoptimiser.connectionCommand" -}}
export CELERY_BROKER_URL="amqp://{{ .Values.runtime.rabbitmq.username }}:${RABBITMQ_PASSWORD}@{{ required "runtime.rabbitmq.host is required" .Values.runtime.rabbitmq.host }}:{{ .Values.runtime.rabbitmq.port }}/";
export CELERY_BACKEND_URL="redis://{{ .Values.runtime.valkey.username }}:${VALKEY_PASSWORD}@{{ required "runtime.valkey.host is required" .Values.runtime.valkey.host }}:{{ .Values.runtime.valkey.port }}/{{ .Values.runtime.valkey.database }}";
{{- end }}

{{- define "fleetoptimiser.serviceAccountName" -}}
{{- if .root.Values.serviceAccount.create }}
{{- printf "%s-%s" (include "fleetoptimiser.fullname" .root) .component | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- "default" }}
{{- end }}
{{- end }}

{{- define "fleetoptimiser.principal" -}}
{{- printf "%s/ns/%s/sa/%s" .root.Values.mesh.trustDomain .root.Release.Namespace (include "fleetoptimiser.serviceAccountName" .) }}
{{- end }}

{{- define "fleetoptimiser.meshInjected" -}}
{{- if and .root.Values.mesh.enabled (index .root.Values.mesh.inject .component) }}true{{ end }}
{{- end }}

{{- define "fleetoptimiser.meshPodLabels" -}}
{{- if .root.Values.mesh.enabled }}
{{- if index .root.Values.mesh.inject .component }}
istio.io/rev: {{ .root.Values.mesh.revision | quote }}
{{- else }}
sidecar.istio.io/inject: "false"
{{- end }}
{{- end }}
{{- end }}
