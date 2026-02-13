# syntax=docker/dockerfile:1.4

# Stage 1: Build the React app
FROM node:18-alpine as build
WORKDIR /app

# Copy package metadata
COPY package*.json ./

# Create node_modules
RUN rm -rf node_modules package-lock.json && \
    npm cache clean --force && \
    npm install --verbose

# Copy rest of the app
COPY . .

# Build production app
RUN npm run build --verbose

# Stage 2: Serve the app using Nginx
FROM nginx:alpine

# Disable SSL verification for apk (corporate proxy issue)
# RUN echo "http://dl-cdn.alpinelinux.org/alpine/v3.23/main" > /etc/apk/repositories && \
#     echo "http://dl-cdn.alpinelinux.org/alpine/v3.23/community" >> /etc/apk/repositories && \
#     apk add --no-cache --allow-untrusted gettext

# Copy build output to Nginx's public directory
COPY --from=build /app/build /usr/share/nginx/html

# Copy the runtime-config template to the serving directory
COPY public/runtime-config.js.template /usr/share/nginx/html/runtime-config.js.template

# Custom Nginx config
COPY nginx.conf /etc/nginx/nginx.conf

# Add entrypoint script for dynamic env injection
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh
EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]