# Stage 1: Build Vite / React app
FROM node:20-alpine AS build
WORKDIR /app

# Accept build arguments for Vite environment variables
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_API_URL=$VITE_API_BASE_URL

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

# Stage 2: Serve via Nginx
FROM nginx:alpine
WORKDIR /usr/share/nginx/html

# Clear existing static assets
RUN rm -rf ./*

# Copy built production assets
COPY --from=build /app/dist .

# Copy custom nginx configuration for SPA routing
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
