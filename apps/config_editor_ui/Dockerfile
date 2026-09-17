# Сборка фронтенда и обслуживание статики nginx-ом.
#
# Внимание: стадия сборки требует доступа к npm-реестру.
# В закрытом контуре собирайте образ там, где реестр доступен (или используйте
# внутреннее зеркало), затем переносите готовый образ.

FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
COPY vendor ./vendor
RUN npm ci

COPY tsconfig.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
