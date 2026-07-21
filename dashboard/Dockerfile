# Multi-stage: build first, then serve with nginx
FROM node:20-alpine AS build
WORKDIR /app
# Copy the manifest and lockfile first so the install layer is only
# rebuilt when dependencies actually change. npm ci installs exactly what
# the lockfile pins, unlike npm install which may resolve newer versions.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# In Docker the backend is reached by hostname - overridable via build-arg
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
