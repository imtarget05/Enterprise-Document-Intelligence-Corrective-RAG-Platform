{{/*
Component fullname: <release>-<component>, matching the k8s/ manifests
(smartdoc-qdrant, smartdoc-llm-router, smartdoc-backend, ...).
Context: dict "root" . "component" "qdrant"
*/}}
{{- define "smartdoc.componentName" -}}
{{- printf "%s-%s" (include "smartdoc.fullname" .root) .component -}}
{{- end -}}

{{- define "smartdoc.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "smartdoc.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "smartdoc.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 -}}
{{- end -}}

{{/*
Standard labels. Context: dict "root" . "component" "x" "role" "api"
*/}}
{{- define "smartdoc.labels" -}}
helm.sh/chart: {{ include "smartdoc.chart" .root }}
{{ include "smartdoc.selectorLabels" . }}
app.kubernetes.io/version: {{ .root.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
{{- end -}}

{{/*
Selector labels — mirror the raw manifests (app + role).
*/}}
{{- define "smartdoc.selectorLabels" -}}
app: {{ include "smartdoc.componentName" . }}
role: {{ .role }}
{{- end -}}

{{/*
Name of the Secret that carries credentials (datasource, JWT, Kafka, R2,
Redis, agent DB, internal token, OIDC issuer).
*/}}
{{- define "smartdoc.secretName" -}}
{{- if .Values.secrets.create -}}
{{- printf "%s-secrets" (include "smartdoc.fullname" .) -}}
{{- else -}}
{{- .Values.secrets.existingName -}}
{{- end -}}
{{- end -}}

{{/*
Pod-level securityContext. Context: dict "runAsUser" 1000 "fsGroup" 1000
*/}}
{{- define "smartdoc.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: {{ .runAsUser }}
{{- if .fsGroup }}
fsGroup: {{ .fsGroup }}
{{- end }}
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/*
Container-level securityContext (hardened, same as raw manifests).
*/}}
{{- define "smartdoc.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

{{/*
Render env[] from a values map. Each key maps to either:
  KEY: "plain-value"
  KEY:
    secretRef:
      name: <optional override>     # default: include "smartdoc.secretName"
      key: <secret key>
      optional: true|false          # default false
NOTE: map iteration is alphabetical; `$(VAR)` expansion (agent REDIS_URL)
relies on REDIS_PASSWORD sorting before REDIS_URL — keep names as-is.
Context: dict "root" $ "env" .Values.x.env
*/}}
{{- define "smartdoc.env" -}}
{{- $root := .root -}}
{{- $secretName := include "smartdoc.secretName" $root -}}
{{- range $name, $spec := .env }}
- name: {{ $name }}
  {{- if kindIs "map" $spec }}
  valueFrom:
    secretKeyRef:
      name: {{ $spec.secretRef.name | default $secretName }}
      key: {{ $spec.secretRef.key }}
      {{- if $spec.secretRef.optional }}
      optional: true
      {{- end }}
  {{- else }}
  value: {{ $spec | quote }}
  {{- end }}
{{- end }}
{{- end -}}

{{/*
Readiness/liveness probes. Context:
dict "root" $ "probes" .Values.x.probes
Each probe: {enabled, type: http|tcpSocket, path, port, initialDelaySeconds,
periodSeconds, failureThreshold}
*/}}
{{- define "smartdoc.probes" -}}
{{- $probes := .probes -}}
{{- range $kind := list "readiness" "liveness" }}
{{- $p := index $probes $kind }}
{{- if $p.enabled }}
{{ $kind }}Probe:
  {{- if eq $p.type "tcpSocket" }}
  tcpSocket:
    port: {{ $p.port }}
  {{- else }}
  httpGet:
    path: {{ $p.path }}
    port: {{ $p.port }}
  {{- end }}
  initialDelaySeconds: {{ $p.initialDelaySeconds }}
  periodSeconds: {{ $p.periodSeconds }}
  {{- if $p.failureThreshold }}
  failureThreshold: {{ $p.failureThreshold }}
  {{- end }}
{{- end }}
{{- end }}
{{- end -}}

{{/*
Deployment strategy helper. Context: dict "strategy" .Values.x.strategy
*/}}
{{- define "smartdoc.strategy" -}}
{{- with .strategy }}
strategy:
  type: {{ .type | default "RollingUpdate" }}
  {{- if .rollingUpdate }}
  rollingUpdate:
    maxUnavailable: {{ .rollingUpdate.maxUnavailable }}
    maxSurge: {{ .rollingUpdate.maxSurge }}
  {{- end }}
{{- end }}
{{- end -}}
