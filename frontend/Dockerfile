FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .

# Vite bakes these into the build at compile time, not runtime -- there's
# no server-side config to inject them into later, so the real Cloud Run
# URLs have to be known before this step runs. scripts/deploy.sh passes
# them in as build-args once the backend services are actually deployed.
ARG VITE_MEMORY_URL
ARG VITE_ACTION_URL
ARG VITE_LIVE_SESSION_GATEWAY_WS_URL
ENV VITE_MEMORY_URL=${VITE_MEMORY_URL}
ENV VITE_ACTION_URL=${VITE_ACTION_URL}
ENV VITE_LIVE_SESSION_GATEWAY_WS_URL=${VITE_LIVE_SESSION_GATEWAY_WS_URL}

RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
