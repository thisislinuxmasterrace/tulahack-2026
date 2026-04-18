<script setup lang="ts">
import PageIntro from '../components/ui/PageIntro.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
</script>

<template>
  <div class="home">
    <PageIntro
      title="Анонимизация голосовых данных"
      subtitle="Загрузите аудиозапись разговора — получите текст с отмеченными персональными данными и обезличенную версию, просмотрите отчёт и при необходимости прослушайте запись с отметками на шкале времени."
    />

    <div class="home__grid">
      <UiCard title="Как это работает" class="home__card">
        <ol class="home__steps">
          <li>Зарегистрируйтесь и загрузите файл.</li>
          <li>Сервис распознает речь и находит чувствительные данные: документы, телефоны, почту и другое.</li>
          <li>Вы смотрите транскрипт с подсветкой и обезличенный текст.</li>
          <li>В отчёте — что именно было скрыто и сколько раз.</li>
        </ol>
        <div class="home__actions">
          <UiButton to="/upload">Загрузить запись</UiButton>
          <UiButton to="/demo" variant="secondary">Посмотреть пример экрана</UiButton>
        </div>
      </UiCard>

      <UiCard title="Подсказка" class="home__card home__card--aside">
        <p class="home__note">
          После входа загрузите файл — откроется страница с результатом. Раздел
          <strong>«Пример экрана»</strong> показывает интерфейс на демонстрационных данных, без загрузки вашего файла.
        </p>
      </UiCard>
    </div>
  </div>
</template>

<style scoped>
.home__grid {
  display: grid;
  gap: 1.25rem;
}

@media (min-width: 840px) {
  .home__grid {
    grid-template-columns: 1.4fr 1fr;
    align-items: start;
  }
}

.home__steps {
  margin: 0 0 1.25rem;
  padding-left: 1.2rem;
  color: var(--text);
  font-size: 0.92rem;
  line-height: 1.55;
}

.home__steps li {
  margin-bottom: 0.45rem;
}

.home__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
}

.home__note {
  font-size: 0.9rem;
  line-height: 1.55;
  color: var(--text-muted);
  margin-bottom: 0.85rem;
}

.home__note strong {
  color: var(--text-strong);
}

</style>
