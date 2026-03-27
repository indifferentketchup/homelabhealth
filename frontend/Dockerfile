FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
# Baked `VITE_APP_MODE`: split UIs use root paths; unset mode keeps legacy /booops /808notes /boolab paths.
ARG VITE_APP_MODE=
ARG VITE_OG_TITLE=
ARG VITE_OG_DESCRIPTION=
ARG VITE_HTML_OG_IMAGE=
ARG VITE_PUBLIC_BOOLAB_URL=
ARG VITE_PUBLIC_BOOOPS_URL=
ARG VITE_PUBLIC_808NOTES_URL=
ENV VITE_APP_MODE=$VITE_APP_MODE
ENV VITE_OG_TITLE=$VITE_OG_TITLE
ENV VITE_OG_DESCRIPTION=$VITE_OG_DESCRIPTION
ENV VITE_HTML_OG_IMAGE=$VITE_HTML_OG_IMAGE
ENV VITE_PUBLIC_BOOLAB_URL=$VITE_PUBLIC_BOOLAB_URL
ENV VITE_PUBLIC_BOOOPS_URL=$VITE_PUBLIC_BOOOPS_URL
ENV VITE_PUBLIC_808NOTES_URL=$VITE_PUBLIC_808NOTES_URL
# Split UI images: pass VITE_APP_MODE so `frontend/.env.<mode>` loads; ENV overrides file defaults.
RUN if [ -z "$VITE_APP_MODE" ]; then npm run build; else npm run build -- --mode "$VITE_APP_MODE"; fi

FROM nginx:alpine
# Runtime: BOOLAB_API_UPSTREAM=host:port (e.g. boolab_api:8000 on Docker net, or 100.x.x.x:9300 on LAN/Tailscale)
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV BOOLAB_API_UPSTREAM=boolab_api:8000
EXPOSE 80
