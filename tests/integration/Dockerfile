FROM php:8.1-apache

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip imagemagick libicu-dev libzip-dev \
    && docker-php-ext-install -j2 intl pdo_mysql zip exif \
    && a2enmod rewrite \
    && rm -rf /var/lib/apt/lists/*

ARG OMEKA_VERSION
RUN case "$OMEKA_VERSION" in 3.2.3|4.1.1|4.2.1) ;; *) exit 1 ;; esac \
    && curl --fail --location --silent --show-error \
        "https://github.com/omeka/omeka-s/releases/download/v${OMEKA_VERSION}/omeka-s-${OMEKA_VERSION}.zip" \
        -o /tmp/omeka.zip \
    && unzip -q /tmp/omeka.zip -d /tmp \
    && mv /tmp/omeka-s /var/www/html/collection \
    && rm /tmp/omeka.zip \
    && chown -R www-data:www-data /var/www/html/collection \
    && printf '<Directory /var/www/html/collection>\nAllowOverride All\n</Directory>\n' \
        > /etc/apache2/conf-enabled/omeka.conf
COPY database.ini /var/www/html/collection/config/database.ini
