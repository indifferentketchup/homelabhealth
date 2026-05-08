FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
ARG VITE_OG_TITLE=
ARG VITE_OG_DESCRIPTION=
ENV VITE_OG_TITLE=$VITE_OG_TITLE
ENV VITE_OG_DESCRIPTION=$VITE_OG_DESCRIPTION
RUN npm run build

FROM nginx:alpine
# Runtime: HLH_API_UPSTREAM=host:port (e.g. hlh_api:8000 on Docker net, or 100.x.x.x:9300 on LAN/Tailscale)
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV HLH_API_UPSTREAM=hlh_api:8000
EXPOSE 80
