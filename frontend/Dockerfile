FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
# Baked `VITE_APP_MODE`: split UIs use root paths; unset mode keeps legacy /booops /808notes /boolab paths.
ARG VITE_APP_MODE=
ARG VITE_PUBLIC_BOOLAB_URL=
ARG VITE_PUBLIC_BOOOPS_URL=
ARG VITE_PUBLIC_808NOTES_URL=
ENV VITE_APP_MODE=$VITE_APP_MODE
ENV VITE_PUBLIC_BOOLAB_URL=$VITE_PUBLIC_BOOLAB_URL
ENV VITE_PUBLIC_BOOOPS_URL=$VITE_PUBLIC_BOOOPS_URL
ENV VITE_PUBLIC_808NOTES_URL=$VITE_PUBLIC_808NOTES_URL
RUN npm run build

FROM nginx:alpine
# Runtime: BOOLAB_API_UPSTREAM=host:port (e.g. boolab_api:8000 on Docker net, or 100.x.x.x:9300 on LAN/Tailscale)
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV BOOLAB_API_UPSTREAM=boolab_api:8000
EXPOSE 80
