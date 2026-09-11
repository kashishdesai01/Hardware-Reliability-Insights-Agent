FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
RUN addgroup -S hria && adduser -S hria -G hria
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER hria
EXPOSE 3000
CMD ["node", "server.js"]
