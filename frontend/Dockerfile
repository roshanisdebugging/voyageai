# Stage 1: Build Vite / React app
FROM node:20-alpine AS build
WORKDIR /app

# Accept build arguments for Vite environment variables
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_API_URL=$VITE_API_BASE_URL
# Google Maps browser key (restricted by HTTP referrer); baked into the static build, so pass it at build time.
ARG VITE_GOOGLE_MAPS_BROWSER_KEY
ENV VITE_GOOGLE_MAPS_BROWSER_KEY=$VITE_GOOGLE_MAPS_BROWSER_KEY

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
