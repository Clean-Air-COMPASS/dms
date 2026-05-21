



FROM node:20-bookworm-slim AS build

WORKDIR /app


COPY package.json package-lock.json ./

RUN npm install --include=optional --no-audit --no-fund \
  && ROLLUP_VERSION=$(node -p "require('./package-lock.json').packages['node_modules/rollup'].version") \
  && npm install --no-save @rollup/rollup-linux-x64-gnu@${ROLLUP_VERSION}


COPY . .

RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
